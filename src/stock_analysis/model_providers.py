from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable


DEFAULT_CODEX_PATHS = (
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
    "codex",
)

DEFAULT_ANTIGRAVITY_PATHS = (
    str(Path.home() / ".local" / "bin" / "agy"),
    "agy",
)


class ProviderError(RuntimeError):
    pass


class ProviderTurnError(ProviderError):
    NON_RESUMABLE_CODES = {"badRequest", "unauthorized", "cyberPolicy", "misalignmentPolicyViolation", "tooManyDenials"}

    def __init__(self, status: str, error: dict[str, Any] | None = None):
        self.status = status
        self.error = error or {}
        self.code = self.error.get("codexErrorInfo")
        message = self.error.get("message") or f"Model turn ended with status {status}"
        details = self.error.get("additionalDetails")
        if details:
            message = f"{message} ({details})"
        super().__init__(message)

    @property
    def resumable(self) -> bool:
        return not isinstance(self.code, str) or self.code not in self.NON_RESUMABLE_CODES


def select_final_agent_message(completed: list[dict[str, Any]], deltas: dict[str, list[str]]) -> str:
    """Select terminal assistant output, excluding progress/commentary messages."""
    for message in reversed(completed):
        if message.get("phase") == "final_answer" and message.get("text", "").strip():
            return message["text"].strip()
    for message in reversed(completed):
        if message.get("text", "").strip():
            return message["text"].strip()
    for chunks in reversed(list(deltas.values())):
        text = "".join(chunks).strip()
        if text:
            return text
    raise ProviderError("Model turn completed without an assistant response")


class ModelProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str, output_schema: dict | None = None) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def get_rate_limits(self) -> dict[str, Any] | None:
        return None

    def get_usage(self) -> dict[str, Any] | None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def find_codex() -> str:
    for candidate in DEFAULT_CODEX_PATHS:
        if Path(candidate).is_file():
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise ProviderError("Codex CLI was not found. Install/open the ChatGPT app or use --provider chatgpt_api.")


def find_executable(name: str, install_hint: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    raise ProviderError(f"{name} CLI was not found. {install_hint}")


def find_antigravity() -> str:
    for candidate in DEFAULT_ANTIGRAVITY_PATHS:
        if Path(candidate).is_file():
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise ProviderError("Antigravity CLI was not found. Install it from antigravity.google and run `agy` once to sign in.")


def _run_json_command(command: list[str], cwd: Path, timeout: int, provider_name: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"{provider_name} CLI timed out after {timeout} seconds") from exc
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise ProviderError(f"{provider_name} CLI failed with exit code {completed.returncode}: {detail[-2000:]}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"{provider_name} CLI returned invalid JSON: {completed.stdout[-1000:]}") from exc
    if not isinstance(result, dict):
        raise ProviderError(f"{provider_name} CLI returned an unexpected response")
    return result


def _request_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int, provider_name: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise ProviderError(f"{provider_name} API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"{provider_name} API request failed: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise ProviderError(f"{provider_name} API returned an unexpected response")
    return result


def claude_draft7_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Translate the 2020-12 features used by our schemas to Claude CLI's Draft 7 dialect."""
    def convert(value: Any) -> Any:
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            if isinstance(value, str) and value.startswith("#/$defs/"):
                return value.replace("#/$defs/", "#/definitions/", 1)
            return value
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$schema":
                continue
            converted["definitions" if key == "$defs" else key] = convert(item)
        return converted

    return convert(schema)


class CodexAppServerProvider(ModelProvider):
    """Use the user's existing ChatGPT/Codex sign-in through app-server."""

    def __init__(self, model: str | None = None, reasoning_effort: str | None = None, cwd: Path | None = None, timeout: int = 900):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.cwd = str((cwd or Path.cwd()).resolve())
        self.timeout = timeout
        self._next_id = 1
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr: list[str] = []
        self._process = subprocess.Popen(
            [find_codex(), "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self._request("initialize", {"clientInfo": {"name": "learn", "title": "Learn Stock Analysis CLI", "version": "0.1.0"}})
        self._notify("initialized", {})

    def _read_stdout(self) -> None:
        assert self._process.stdout
        for line in self._process.stdout:
            try:
                self._messages.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _read_stderr(self) -> None:
        assert self._process.stderr
        for line in self._process.stderr:
            self._stderr.append(line.rstrip())

    def _send(self, message: dict) -> None:
        if self._process.poll() is not None:
            raise ProviderError("Codex app-server stopped unexpectedly: " + "\n".join(self._stderr[-8:]))
        assert self._process.stdin
        self._process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self._process.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._send({"method": method, "params": params})

    def _request(self, method: str, params: dict) -> dict:
        request_id = self._next_id
        self._next_id += 1
        self._send({"id": request_id, "method": method, "params": params})
        while True:
            try:
                message = self._messages.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise ProviderError(f"Timed out waiting for {method}") from exc
            if message.get("id") == request_id:
                if "error" in message:
                    raise ProviderError(f"{method} failed: {message['error']}")
                return message.get("result", {})
            # Notifications may arrive before the matching response. They are
            # informational for setup requests and must not be re-queued (that
            # would starve the response behind the same notification).

    def complete(self, prompt: str, output_schema: dict | None = None) -> str:
        thread_params: dict[str, Any] = {
            "cwd": self.cwd,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
        }
        if self.model:
            thread_params["model"] = self.model
        thread = self._request("thread/start", thread_params)
        thread_id = thread.get("thread", {}).get("id") or thread.get("threadId")
        if not thread_id:
            raise ProviderError(f"thread/start returned no thread id: {thread}")
        turn_id = self._next_id
        self._next_id += 1
        params: dict[str, Any] = {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]}
        if self.reasoning_effort:
            params["effort"] = self.reasoning_effort
        if output_schema:
            params["outputSchema"] = output_schema
        self._send({"id": turn_id, "method": "turn/start", "params": params})
        deltas: dict[str, list[str]] = {}
        completed_messages: list[dict[str, Any]] = []
        turn_started = False
        while True:
            try:
                message = self._messages.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise ProviderError("Timed out waiting for model response") from exc
            if message.get("id") == turn_id:
                if "error" in message:
                    raise ProviderError(f"turn/start failed: {message['error']}")
                turn_started = True
                continue
            method = message.get("method", "")
            payload = message.get("params", {})
            if method == "item/agentMessage/delta":
                deltas.setdefault(payload.get("itemId", "unknown"), []).append(payload.get("delta", ""))
            elif method == "item/completed":
                item = payload.get("item", {})
                if item.get("type") == "agentMessage":
                    completed_messages.append(item)
            elif method == "turn/completed" and turn_started:
                turn = payload.get("turn", {})
                status = turn.get("status")
                if status not in {"completed", None}:
                    raise ProviderTurnError(status or "failed", turn.get("error"))
                return select_final_agent_message(completed_messages, deltas)

    def get_rate_limits(self) -> dict[str, Any]:
        return self._request(
            "account/rateLimits/read",
            {"excludeResetCreditDetails": True, "supportsLunaReserve": False},
        )

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()


class OpenAIAPIProvider(ModelProvider):
    def __init__(self, model: str | None = None, reasoning_effort: str | None = None, timeout: int = 900):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-5.4")
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is required when --provider chatgpt_api is selected")

    def complete(self, prompt: str, output_schema: dict | None = None) -> str:
        payload: dict[str, Any] = {"model": self.model, "input": prompt}
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if output_schema:
            payload["text"] = {"format": {"type": "json_schema", "name": "stock_analysis", "schema": output_schema, "strict": True}}
        result = _request_json(
            "https://api.openai.com/v1/responses",
            payload,
            {"Authorization": f"Bearer {self.api_key}"},
            self.timeout,
            "OpenAI",
        )
        texts = [part.get("text", "") for item in result.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text"]
        if not texts:
            raise ProviderError("OpenAI API response contained no output text")
        return "".join(texts)


class ClaudeCLIProvider(ModelProvider):
    """Use Claude Code's existing subscription login in non-interactive mode."""

    def __init__(self, model: str = "sonnet", reasoning_effort: str | None = None, cwd: Path | None = None, timeout: int = 900):
        self.executable = find_executable("claude", "Install Claude Code and run `claude` once to sign in, or use --provider claude_api.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.cwd = (cwd or Path.cwd()).resolve()
        self.timeout = timeout

    def complete(self, prompt: str, output_schema: dict | None = None) -> str:
        command = [
            self.executable, "--print", prompt, "--output-format", "json",
            "--model", self.model, "--permission-mode", "plan", "--no-session-persistence",
        ]
        if self.reasoning_effort and self.reasoning_effort != "none":
            command.extend(["--effort", self.reasoning_effort])
        if output_schema:
            schema = claude_draft7_schema(output_schema)
            command.extend(["--json-schema", json.dumps(schema, separators=(",", ":"))])
        result = _run_json_command(command, self.cwd, self.timeout, "Claude")
        if result.get("is_error") or result.get("subtype", "").startswith("error"):
            raise ProviderError(f"Claude CLI model turn failed: {result.get('result') or result.get('errors') or result}")
        if output_schema and result.get("structured_output") is not None:
            return json.dumps(result["structured_output"], ensure_ascii=False)
        text = result.get("result") or result.get("response")
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("Claude CLI response contained no model output")
        return text.strip()


class AnthropicAPIProvider(ModelProvider):
    def __init__(self, model: str = "claude-sonnet-5-5", reasoning_effort: str | None = None, timeout: int = 900):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("ANTHROPIC_MODEL", model)
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is required when --provider claude_api is selected")

    def complete(self, prompt: str, output_schema: dict | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 20000,
            "messages": [{"role": "user", "content": prompt}],
        }
        output_config: dict[str, Any] = {}
        if self.reasoning_effort and self.reasoning_effort != "none":
            output_config["effort"] = self.reasoning_effort
        if output_schema:
            output_config["format"] = {"type": "json_schema", "schema": claude_draft7_schema(output_schema)}
        if output_config:
            payload["output_config"] = output_config
        result = _request_json(
            "https://api.anthropic.com/v1/messages",
            payload,
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            self.timeout,
            "Anthropic",
        )
        texts = [block.get("text", "") for block in result.get("content", []) if block.get("type") == "text"]
        if not texts:
            raise ProviderError("Anthropic API response contained no output text")
        return "".join(texts)


class GeminiCLIProvider(ModelProvider):
    """Use Gemini CLI's existing Google login in headless mode."""

    def __init__(self, model: str = "pro", reasoning_effort: str | None = None, cwd: Path | None = None, timeout: int = 900):
        self.executable = find_executable("gemini", "Install Gemini CLI and run `gemini` once to sign in, or use --provider gemini_api.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.cwd = (cwd or Path.cwd()).resolve()
        self.timeout = timeout

    def complete(self, prompt: str, output_schema: dict | None = None) -> str:
        if output_schema:
            prompt += "\n\nReturn only JSON matching this JSON Schema exactly:\n" + json.dumps(output_schema, separators=(",", ":"))
        command = [
            self.executable, "--prompt", prompt, "--output-format", "json",
            "--model", self.model, "--approval-mode", "plan", "--skip-trust",
        ]
        result = _run_json_command(command, self.cwd, self.timeout, "Gemini")
        if result.get("error"):
            raise ProviderError(f"Gemini CLI model turn failed: {result['error']}")
        text = result.get("response")
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("Gemini CLI response contained no model output")
        return text.strip()


class GeminiAPIProvider(ModelProvider):
    def __init__(self, model: str = "gemini-2.5-pro", reasoning_effort: str | None = None, timeout: int = 900):
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model = os.environ.get("GEMINI_MODEL", model)
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY (or GOOGLE_API_KEY) is required when --provider gemini_api is selected")

    def complete(self, prompt: str, output_schema: dict | None = None) -> str:
        payload: dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if output_schema:
            payload["generationConfig"] = {
                "responseMimeType": "application/json",
                "responseJsonSchema": output_schema,
            }
        model = urllib.parse.quote(self.model, safe="-._")
        result = _request_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            payload,
            {"x-goog-api-key": self.api_key},
            self.timeout,
            "Gemini",
        )
        texts = [
            part.get("text", "")
            for candidate in result.get("candidates", [])
            for part in candidate.get("content", {}).get("parts", [])
            if "text" in part
        ]
        if not texts:
            feedback = result.get("promptFeedback") or result
            raise ProviderError(f"Gemini API response contained no output text: {feedback}")
        return "".join(texts)


class AntigravityCLIProvider(ModelProvider):
    """Use Antigravity CLI's cached Google login and free/subscription allowance."""

    def __init__(
        self,
        model: str = "gemini-3.8-flash-medium",
        reasoning_effort: str | None = None,
        cwd: Path | None = None,
        timeout: int = 900,
        on_retry: Callable[[str], None] | None = None,
    ):
        self.executable = find_antigravity()
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.cwd = (cwd or Path.cwd()).resolve()
        self.timeout = timeout
        self.on_retry = on_retry
        self._calls: list[dict[str, Any]] = []
        self._attempts: list[dict[str, Any]] = []

    @staticmethod
    def _effort(value: str | None) -> str:
        if value in {"medium"}:
            return "medium"
        if value in {"high", "xhigh", "max"}:
            return "high"
        return "low"

    def complete(self, prompt: str, output_schema: dict | None = None) -> str:
        command = [
            self.executable, "--print", prompt, "--output-format", "json",
            "--model", self.model, "--print-timeout", f"{max(1, self.timeout // 60)}m",
        ]
        if not self.model.endswith(("-low", "-medium", "-high")):
            command.extend(["--effort", self._effort(self.reasoning_effort)])
        if output_schema:
            schema = claude_draft7_schema(output_schema)
            command.extend(["--json-schema", json.dumps(schema, separators=(",", ":"))])
        for attempt_number in (1, 2):
            result = _run_json_command(command, self.cwd, self.timeout + 30, "Antigravity")
            usage = result.get("usage")
            if isinstance(usage, dict):
                self._calls.append(usage)
            text = result.get("response")
            structured = result.get("structured_output")
            self._attempts.append({
                "attempt": attempt_number,
                "conversation_id": result.get("conversation_id"),
                "status": result.get("status"),
                "error": result.get("error"),
                "response_characters": len(text) if isinstance(text, str) else 0,
                "structured_output_present": structured is not None,
                "usage": usage if isinstance(usage, dict) else None,
            })
            if result.get("status") != "SUCCESS":
                raise ProviderError(f"Antigravity CLI model turn failed: {result.get('error') or result.get('status') or result}")
            if output_schema and structured is not None:
                return json.dumps(structured, ensure_ascii=False)
            if isinstance(text, str) and text.strip():
                return text.strip()
            if attempt_number == 1 and self.on_retry:
                self.on_retry("Antigravity returned SUCCESS without model output; retrying this model turn once")
        raise ProviderTurnError(
            "failed",
            {"message": "Antigravity returned SUCCESS without model output twice", "codexErrorInfo": "emptyModelOutput"},
        )

    def get_usage(self) -> dict[str, Any]:
        keys = ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens")
        totals = {key: sum(int(call.get(key, 0) or 0) for call in self._calls) for key in keys}
        return {
            "provider": "antigravity", "model": self.model,
            "calls": self._calls, "attempts": self._attempts, "totals": totals,
        }


class DryRunProvider(ModelProvider):
    """Deterministic provider for testing the complete pipeline without tokens."""

    def complete(self, prompt: str, output_schema: dict | None = None) -> str:
        properties = (output_schema or {}).get("properties", {})
        if "weighted_score" in properties:
            return json.dumps({
                "company_name": "Dry-run company", "stance": "neutral", "weighted_score": 0,
                "confidence": "low", "rationale": "Dry run: no model research was performed.",
                "specialist_scores": {
                    role: {"score": 0, "confidence": "low"}
                    for role in ("fundamentals", "valuation", "technicals", "catalysts", "risks")
                },
                "executive_summary": "This validates the orchestration and rendering pipeline only.",
                "company_profile": "Supply a live provider to generate researched content.",
                "industry_overview": "Not evaluated in dry-run mode.", "technicals": "Not evaluated.",
                "fundamentals": "Not evaluated.", "valuation": "Not evaluated.",
                "risks": "Missing live research is the primary limitation.", "catalysts": "Not evaluated.",
                "sector_and_peers": "Not evaluated.", "bull_case": "Not evaluated.", "bear_case": "Not evaluated.",
                "reference_price": "N/A", "price_as_of": "N/A", "market_valuation": "N/A",
                "next_key_date": "N/A", "sources": [], "limitations": ["Dry-run output"],
            })
        return json.dumps({
            "score": 0, "confidence": "low", "findings": ["Dry-run response"],
            "evidence": [], "sources": [], "bull_scenario": "Not evaluated.",
            "bear_scenario": "Not evaluated.", "risks": ["No live model was used"],
            "missing_data": ["All live research"], "invalidation": ["Not applicable"],
        })

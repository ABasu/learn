import unittest
from pathlib import Path
from unittest.mock import patch

from stock_analysis.model_providers import (
    AnthropicAPIProvider,
    AntigravityCLIProvider,
    ClaudeCLIProvider,
    GeminiAPIProvider,
    GeminiCLIProvider,
    claude_draft7_schema,
    select_final_agent_message,
)


class ModelProviderTest(unittest.TestCase):
    def test_prefers_final_answer_over_commentary(self):
        messages = [
            {"phase": "commentary", "text": '{"score": 0}'},
            {"phase": "final_answer", "text": '{"score": 1.25}'},
        ]
        self.assertEqual(select_final_agent_message(messages, {}), '{"score": 1.25}')

    def test_falls_back_to_last_completed_message(self):
        messages = [{"phase": None, "text": "first"}, {"phase": None, "text": "last"}]
        self.assertEqual(select_final_agent_message(messages, {}), "last")

    def test_converts_2020_schema_to_claude_draft7(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"score": {"type": "number"}},
            "properties": {"score": {"$ref": "#/$defs/score"}},
        }
        converted = claude_draft7_schema(schema)
        self.assertNotIn("$schema", converted)
        self.assertEqual(converted["definitions"], {"score": {"type": "number"}})
        self.assertEqual(converted["properties"]["score"]["$ref"], "#/definitions/score")

    @patch("stock_analysis.model_providers._run_json_command")
    @patch("stock_analysis.model_providers.find_executable", return_value="/usr/local/bin/claude")
    def test_claude_cli_returns_structured_output(self, _find, run):
        run.return_value = {"subtype": "success", "structured_output": {"score": 1}}
        provider = ClaudeCLIProvider("sonnet", "medium", Path("/tmp"))
        self.assertEqual(provider.complete("prompt", {"type": "object"}), '{"score": 1}')
        command = run.call_args.args[0]
        self.assertIn("--json-schema", command)
        self.assertIn("--effort", command)

    @patch("stock_analysis.model_providers._run_json_command")
    @patch("stock_analysis.model_providers.find_executable", return_value="/usr/local/bin/gemini")
    def test_gemini_cli_returns_response(self, _find, run):
        run.return_value = {"response": '{"score": 1}', "stats": {}}
        provider = GeminiCLIProvider("pro", "medium", Path("/tmp"))
        self.assertEqual(provider.complete("prompt", {"type": "object"}), '{"score": 1}')
        command = run.call_args.args[0]
        self.assertIn("--output-format", command)
        self.assertIn("--approval-mode", command)

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=True)
    @patch("stock_analysis.model_providers._request_json")
    def test_anthropic_api_uses_schema_and_effort(self, request):
        request.return_value = {"content": [{"type": "text", "text": '{"score":1}'}]}
        provider = AnthropicAPIProvider("claude-sonnet-5-5", "high")
        self.assertEqual(provider.complete("prompt", {"type": "object"}), '{"score":1}')
        payload = request.call_args.args[1]
        self.assertEqual(payload["output_config"]["effort"], "high")
        self.assertEqual(payload["output_config"]["format"]["type"], "json_schema")

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True)
    @patch("stock_analysis.model_providers._request_json")
    def test_gemini_api_uses_json_schema(self, request):
        request.return_value = {"candidates": [{"content": {"parts": [{"text": '{"score":1}'}]}}]}
        provider = GeminiAPIProvider("gemini-2.5-pro", "medium")
        self.assertEqual(provider.complete("prompt", {"type": "object"}), '{"score":1}')
        payload = request.call_args.args[1]
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["responseJsonSchema"], {"type": "object"})

    @patch("stock_analysis.model_providers._run_json_command")
    @patch("stock_analysis.model_providers.find_antigravity", return_value="/Users/test/.local/bin/agy")
    def test_antigravity_uses_schema_effort_and_tracks_tokens(self, _find, run):
        run.return_value = {
            "status": "SUCCESS",
            "structured_output": {"score": 1},
            "usage": {
                "input_tokens": 100, "output_tokens": 10, "thinking_tokens": 5,
                "cache_read_tokens": 20, "total_tokens": 115,
            },
        }
        provider = AntigravityCLIProvider("claude-sonnet-4-6", "xhigh", Path("/tmp"))
        self.assertEqual(provider.complete("prompt", {"type": "object"}), '{"score": 1}')
        command = run.call_args.args[0]
        self.assertIn("--json-schema", command)
        self.assertEqual(command[command.index("--effort") + 1], "high")
        self.assertEqual(provider.get_usage()["totals"]["total_tokens"], 115)

    @patch("stock_analysis.model_providers._run_json_command")
    @patch("stock_analysis.model_providers.find_antigravity", return_value="/Users/test/.local/bin/agy")
    def test_antigravity_does_not_duplicate_model_encoded_effort(self, _find, run):
        run.return_value = {"status": "SUCCESS", "response": "ok", "usage": {"total_tokens": 1}}
        provider = AntigravityCLIProvider("gemini-3.8-flash-medium", "low", Path("/tmp"))
        self.assertEqual(provider.complete("prompt"), "ok")
        self.assertNotIn("--effort", run.call_args.args[0])

    @patch("stock_analysis.model_providers._run_json_command")
    @patch("stock_analysis.model_providers.find_antigravity", return_value="/Users/test/.local/bin/agy")
    def test_antigravity_retries_one_empty_success(self, _find, run):
        run.side_effect = [
            {"status": "SUCCESS", "response": "", "usage": {"total_tokens": 5}},
            {"status": "SUCCESS", "structured_output": {"score": 1}, "usage": {"total_tokens": 7}},
        ]
        notices = []
        provider = AntigravityCLIProvider("gemini-3.8-flash-medium", "low", Path("/tmp"), on_retry=notices.append)
        self.assertEqual(provider.complete("prompt", {"type": "object"}), '{"score": 1}')
        self.assertEqual(run.call_count, 2)
        self.assertEqual(provider.get_usage()["totals"]["total_tokens"], 12)
        self.assertEqual(len(provider.get_usage()["attempts"]), 2)
        self.assertEqual(len(notices), 1)


if __name__ == "__main__":
    unittest.main()

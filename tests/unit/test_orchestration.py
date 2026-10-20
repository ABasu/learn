import io
import logging
import tempfile
import time
import unittest
from pathlib import Path

from stock_analysis.domain import ReportRequest
from stock_analysis.model_providers import DryRunProvider, ProviderTurnError
from stock_analysis.orchestration.runner import _heartbeat, calculate_weighted_score, extract_json_object, load_checkpoint, run_analysis, validate_specialist


class OrchestrationTest(unittest.TestCase):
    def test_checkpoint_resumes_at_final_adjudicator(self):
        class FailFinalProvider(DryRunProvider):
            def __init__(self):
                self.calls = 0

            def complete(self, prompt, output_schema=None):
                self.calls += 1
                if self.calls == 8:
                    raise ProviderTurnError("failed", {"message": "usage exhausted", "codexErrorInfo": "usageLimitExceeded"})
                return super().complete(prompt, output_schema)

        request = ReportRequest("TESTCO", "nse")
        with tempfile.TemporaryDirectory() as directory:
            checkpoint_path = Path(directory) / "checkpoint.json"
            with self.assertRaises(ProviderTurnError):
                run_analysis(FailFinalProvider(), request, checkpoint_path=checkpoint_path)
            state = load_checkpoint(checkpoint_path, request)
            self.assertEqual(state["next_stage"], "adjudicator:final")
            self.assertEqual(len(state["specialists"]), 5)
            self.assertEqual(len(state["scenarios"]), 2)
            report, _ = run_analysis(DryRunProvider(), request, checkpoint_path=checkpoint_path, resume_state=state)
            self.assertEqual(report["ticker"], "TESTCO")
            self.assertEqual(load_checkpoint(checkpoint_path, request)["status"], "complete")

    def test_calculates_score_from_configured_components(self):
        scores = {
            "fundamentals": {"score": 0.5}, "valuation": {"score": -0.5},
            "technicals": {"score": -0.75}, "catalysts": {"score": 0.25},
            "risks": {"score": -0.5},
        }
        self.assertEqual(calculate_weighted_score(scores), -0.14)

    def test_heartbeat_reports_long_running_stage(self):
        stream = io.StringIO()
        logger = logging.getLogger("heartbeat-test")
        logger.handlers = [logging.StreamHandler(stream)]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        with _heartbeat(logger, "fundamentals", interval=0.01):
            time.sleep(0.025)
        self.assertIn("Still working: fundamentals", stream.getvalue())

    def test_extracts_fenced_json(self):
        self.assertEqual(extract_json_object('```json\n{"score": 1}\n```'), {"score": 1})

    def test_extracts_final_object_when_transport_appends_content(self):
        response = '{"score": 1}{"score": 2}\nAdditional transport text'
        self.assertEqual(extract_json_object(response), {"score": 2})

    def test_enforces_common_contract(self):
        value = {
            "score": 1, "confidence": "medium", "findings": ["x"], "evidence": ["y"],
            "sources": ["https://example.com"], "bull_scenario": "up", "bear_scenario": "down",
            "risks": ["r"], "missing_data": [], "invalidation": ["i"],
        }
        validate_specialist(value)
        value["score"] = 3
        with self.assertRaises(ValueError):
            validate_specialist(value)


if __name__ == "__main__":
    unittest.main()


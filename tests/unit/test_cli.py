import unittest
from unittest.mock import patch

from stock_analysis.cli.main import _generate, build_parser, parse_tickers
from stock_analysis.model_providers import ProviderTurnError


class CliHelpTest(unittest.TestCase):
    def test_parses_comma_separated_tickers(self):
        self.assertEqual(parse_tickers(" apollo,RELIANCE "), ["APOLLO", "RELIANCE"])

    def test_rejects_duplicate_tickers(self):
        with self.assertRaises(ValueError):
            parse_tickers("RELIANCE,reliance")

    def test_batch_stops_gracefully_on_resumable_provider_failure(self):
        args = build_parser().parse_args(["generate", "--ticker", "ONE,TWO,THREE", "--exchange", "nse", "--dry-run"])
        failure = ProviderTurnError("failed", {"message": "usage exhausted", "codexErrorInfo": "usageLimitExceeded"})
        failure.run_dir = "/tmp/run-two"
        failure.resume_command = "uv run learn generate --ticker TWO --exchange nse --resume /tmp/run-two"
        with patch("stock_analysis.cli.main._generate_one", side_effect=[{"ticker": "ONE"}, failure]) as generate_one:
            self.assertEqual(_generate(args), 75)
        self.assertEqual(generate_one.call_count, 2)

    def test_root_help_includes_all_generate_options(self):
        help_text = build_parser().format_help()
        self.assertIn("GENERATE COMMAND", help_text)
        self.assertIn("--reasoning-effort", help_text)
        self.assertIn("--research-file", help_text)
        self.assertIn("--verbose", help_text)
        self.assertIn("--quiet", help_text)
        self.assertIn("--resume", help_text)
        self.assertIn("Configuration precedence", help_text)
        self.assertIn("chatgpt_api", help_text)
        self.assertIn("claude_api", help_text)
        self.assertIn("gemini_api", help_text)
        self.assertIn("antigravity", help_text)
        self.assertIn("claude=sonnet", help_text)
        self.assertIn("antigravity=gemini-3.8-flash-medium", help_text)

    def test_provider_specific_model_is_selected_when_model_is_omitted(self):
        args = build_parser().parse_args(["generate", "--ticker", "IBM", "--exchange", "nyse", "--provider", "claude"])
        self.assertFalse(hasattr(args, "model"))


if __name__ == "__main__":
    unittest.main()

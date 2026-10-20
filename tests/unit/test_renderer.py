import tempfile
import unittest
from pathlib import Path

from stock_analysis.reports.renderer import render_report


class RendererTest(unittest.TestCase):
    def test_writes_visible_and_machine_readable_score(self):
        report = {"ticker": "TEST", "exchange": "NSE", "weighted_score": 0.75, "stance": "neutral", "confidence": "medium"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.html"
            render_report(report, output)
            content = output.read_text()
        self.assertIn('data-analysis-score="+0.75"', content)
        self.assertIn('id="analysis-metadata"', content)


if __name__ == "__main__":
    unittest.main()

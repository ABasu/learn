import unittest

from stock_analysis.domain import ReportRequest


class ReportRequestTest(unittest.TestCase):
    def test_normalizes_ticker_and_exchange(self):
        request = ReportRequest(" pidilitind ", "NSE")
        self.assertEqual(request.ticker, "PIDILITIND")
        self.assertEqual(request.exchange, "nse")
        self.assertEqual(request.country, "india")

    def test_rejects_unknown_exchange(self):
        with self.assertRaises(ValueError):
            ReportRequest("AAPL", "lse")


if __name__ == "__main__":
    unittest.main()


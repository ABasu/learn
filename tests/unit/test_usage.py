import unittest

from stock_analysis.usage import five_hour_usage, format_usage


class UsageTest(unittest.TestCase):
    def test_selects_model_five_hour_window(self):
        snapshot = {
            "ordinaryUsageAllowed": True,
            "rateLimitsByLimitId": {
                "codex": {
                    "normalModelSlug": "gpt-5.6-terra",
                    "primary": {"usedPercent": 37, "windowDurationMins": 300, "resetsAt": 1_800_000_000},
                    "secondary": {"usedPercent": 12, "windowDurationMins": 10080, "resetsAt": 1_800_500_000},
                }
            },
        }
        usage = five_hour_usage(snapshot, "gpt-5.6-terra")
        self.assertEqual(usage["used_percent"], 37)
        self.assertEqual(usage["remaining_percent"], 63)
        self.assertIn("37% used", format_usage("before", usage))

    def test_formats_percentage_point_delta(self):
        before = {"used_percent": 20, "remaining_percent": 80, "resets_at": None}
        after = {"used_percent": 24, "remaining_percent": 76, "resets_at": None}
        self.assertIn("+4 percentage points", format_usage("after", after, before))


if __name__ == "__main__":
    unittest.main()

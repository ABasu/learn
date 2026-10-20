import tempfile
import unittest
from pathlib import Path

from stock_analysis.config import load_model_defaults


class ModelConfigTest(unittest.TestCase):
    def test_loads_model_and_effort(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.yaml"
            path.write_text("defaults:\n  model: gpt-5.6-sol\n  reasoning_effort: medium\navailable_models:\n  - gpt-5.6-sol\n  - gpt-5.6-luna\n")
            defaults = load_model_defaults(path)
        self.assertEqual(defaults.model, "gpt-5.6-sol")
        self.assertEqual(defaults.reasoning_effort, "medium")
        self.assertEqual(defaults.available_models, ("gpt-5.6-sol", "gpt-5.6-luna"))

    def test_rejects_invalid_effort(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.yaml"
            path.write_text("defaults:\n  model: gpt-5.6-sol\n  reasoning_effort: enormous\n")
            with self.assertRaises(ValueError):
                load_model_defaults(path)

    def test_loads_provider_specific_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.yaml"
            path.write_text(
                "defaults:\n  model: gpt-5.6-sol\n  reasoning_effort: low\n"
                "available_models:\n  - gpt-5.6-sol\n"
                "provider_defaults:\n  claude: sonnet\n"
                "provider_models:\n  claude:\n    - sonnet\n    - opus\n"
            )
            defaults = load_model_defaults(path)
        self.assertEqual(defaults.model_for("claude"), "sonnet")
        self.assertEqual(defaults.models_for("claude"), ("sonnet", "opus"))


if __name__ == "__main__":
    unittest.main()

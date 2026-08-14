import importlib.util
import pathlib
import unittest
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "take_online_exam.py"
SPEC = importlib.util.spec_from_file_location("take_online_exam", SCRIPT)
assert SPEC and SPEC.loader
take_online_exam = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(take_online_exam)


class PreflightTests(unittest.TestCase):
    def test_preflight_does_not_require_a_specific_agent_cli(self):
        with patch.object(take_online_exam.shutil, "which", return_value=None):
            report = take_online_exam.preflight("test-session")

        self.assertNotIn("codex", report)
        self.assertFalse(any("Codex CLI" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()

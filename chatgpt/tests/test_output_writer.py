import json
import tempfile
import unittest
from pathlib import Path

from src.reporting.output_writer import output_path, write_stage_output


class OutputWriterTest(unittest.TestCase):
    def test_writes_chatgpt_stage_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            path = write_stage_output(repo_root, 2, {"status": "test"})
            loaded = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(path, output_path(repo_root, 2))
        self.assertEqual(loaded["stage_number"], 2)
        self.assertEqual(loaded["status"], "test")
        self.assertIn("generated_at_utc", loaded)


if __name__ == "__main__":
    unittest.main()


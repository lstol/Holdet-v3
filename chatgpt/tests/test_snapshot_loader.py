import json
import tempfile
import unittest
from pathlib import Path

from src.ingest.snapshot_loader import load_snapshot, snapshot_path


VALID_SNAPSHOT = {
    "holdet_ids": {},
    "current_prices": {},
    "is_out": {},
    "post_stage_results": {},
    "jersey_holders": {},
    "gc_standings": [],
    "team_composition": [],
    "bank_balance": 0,
    "stage_metadata": {"stage": 1},
}


class SnapshotLoaderTest(unittest.TestCase):
    def test_loads_canonical_stage_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            path = snapshot_path(repo_root, 1)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(VALID_SNAPSHOT), encoding="utf-8")

            loaded = load_snapshot(repo_root, 1)

        self.assertEqual(loaded["stage_metadata"]["stage"], 1)

    def test_rejects_missing_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            path = snapshot_path(repo_root, 1)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"stage_metadata": {}}), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_snapshot(repo_root, 1)


if __name__ == "__main__":
    unittest.main()


import json
import tempfile
import unittest
from pathlib import Path

from src.ingest.rider_loader import (
    compare_snapshot_holdet_ids,
    load_rider_universe,
    rider_universe_path,
    validate_riders,
    write_dashboard_rider_artifact,
)


def write_universe(repo_root: Path, riders: list[dict]) -> Path:
    path = rider_universe_path(repo_root)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"meta": {"race": "giro2026"}, "riders": riders}), encoding="utf-8")
    return path


class RiderLoaderTest(unittest.TestCase):
    def test_loads_and_summarizes_giro_riders(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            write_universe(
                repo_root,
                [
                    {"holdet_id": 1, "name": "Rider A", "team": "AAA", "price": 3_000_000},
                    {"holdet_id": 2, "name": "Rider B", "team": "BBB", "price": 5_000_000},
                    {"holdet_id": 3, "name": "Rider C", "team": "BBB", "price": 7_000_000},
                ],
            )

            universe = load_rider_universe(repo_root)

        self.assertEqual(universe.summary["rider_count"], 3)
        self.assertEqual(universe.summary["team_count"], 2)
        self.assertEqual(universe.summary["median_price"], 5_000_000)
        self.assertTrue(universe.validation["is_valid"])
        self.assertEqual(universe.riders[0]["team_code"], None)

    def test_validation_flags_bad_rows(self):
        riders = [
            {"holdet_id": 1, "name": "Rider A", "team": "AAA", "price": 3_000_000},
            {"holdet_id": 1, "name": "", "team": "AAA", "price": 0},
            {"holdet_id": None, "name": "Rider C", "team": "BBB", "price": "bad"},
        ]

        validation = validate_riders(riders)

        self.assertFalse(validation["is_valid"])
        self.assertEqual(validation["duplicate_ids"], [1])
        self.assertEqual(validation["missing_id_rows"], [2])
        self.assertEqual(validation["missing_name_rows"], [1])
        self.assertEqual(validation["invalid_price_rows"], [1, 2])

    def test_compares_snapshot_ids_for_current_snapshot_shape(self):
        riders = [
            {"holdet_id": 1, "name": "Rider A", "team": "AAA", "price": 3_000_000},
            {"holdet_id": 2, "name": "Rider B", "team": "BBB", "price": 5_000_000},
        ]
        snapshot = {"riders": [{"holdet_id": 2}, {"holdet_id": 3}]}

        comparison = compare_snapshot_holdet_ids(riders, snapshot)

        self.assertFalse(comparison["is_match"])
        self.assertEqual(comparison["missing_from_snapshot"], [1])
        self.assertEqual(comparison["missing_from_universe"], [3])

    def test_writes_dashboard_artifact_under_chatgpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            write_universe(repo_root, [{"holdet_id": 1, "name": "Rider A", "team": "AAA", "price": 3_000_000}])
            universe = load_rider_universe(repo_root)

            path = write_dashboard_rider_artifact(repo_root, universe)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(path, repo_root / "chatgpt" / "dashboard" / "data" / "riders_giro_2026.json")
        self.assertEqual(payload["summary"]["rider_count"], 1)
        self.assertEqual(payload["riders"][0]["holdet_id"], 1)


if __name__ == "__main__":
    unittest.main()

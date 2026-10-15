"""Mixed disclosure rules must survive aggregation into reader-facing advice."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from consensus import compute


class DisclosureTests(unittest.TestCase):
    def row(self, disclosures):
        entities = [{"name": str(i), "policies": [{"axis": "translation", "permission": "permitted",
                    "disclosure": d}]} for i, d in enumerate(disclosures)]
        axes = {"translation": {"title": "Translation", "group": "stm"}}
        raw = {"activities": [{"key": "translation", "plain": "Translation"}], "extended_axes": []}
        return compute(entities, axes, raw)["rows"][0]

    def test_required_majority_does_not_erase_optional_disclosure(self):
        row = self.row(["required"] * 3 + ["encouraged"] * 2)
        self.assertEqual(row["band"], "universal")  # agreement on permission, not disclosure
        self.assertEqual(row["disclosure_counts"], {"required": 3, "encouraged": 2})
        self.assertIn("disclosure requirements vary", row["rule"])
        self.assertNotIn("must be declared", row["rule"])

    def test_unanimous_disclosure_remains_explicit(self):
        row = self.row(["required"] * 4)
        self.assertFalse(row["disclosure_varies"])
        self.assertIn("must be declared", row["rule"])


if __name__ == "__main__":
    unittest.main()

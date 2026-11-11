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

class ScopeTests(unittest.TestCase):
    def compute_rows(self, entities):
        axes = {'reviewer_use': {'title': 'Reviewing', 'group': 'extended'}}
        raw = {'activities': [], 'extended_axes': [{'key': 'reviewer_use', 'plain': 'Reviewing'}]}
        return compute(entities, axes, raw)['rows'][0]

    def entity(self, name, permission, kind='publisher', architecture='prose'):
        return {'name': name, 'type': kind, 'policy_architecture': architecture,
                'policies': [{'axis': 'reviewer_use', 'permission': permission,
                              'disclosure': 'not_addressed'}]}

    def test_recommendation_is_not_a_prohibition(self):
        row = self.compute_rows([self.entity('A', 'prohibited'), self.entity('B', 'prohibited'),
                                 self.entity('C', 'discouraged'), self.entity('D', 'discouraged')])
        self.assertEqual(row['band'], 'split')
        self.assertTrue(row['tied'])
        self.assertIsNone(row['rule'])

    def test_other_authorities_do_not_vote_as_journals(self):
        entities = [self.entity(str(i), 'permitted') for i in range(4)]
        entities += [self.entity('Funder', 'prohibited', 'funder'),
                     self.entity('Preprint', 'prohibited', 'preprint_server'),
                     self.entity('Advice', 'prohibited', 'normative_body'),
                     self.entity('Taxonomy', 'prohibited', architecture='classification_only')]
        row = self.compute_rows(entities)
        self.assertEqual((row['n'], row['total']), (4, 4))
        self.assertEqual(row['band'], 'universal')

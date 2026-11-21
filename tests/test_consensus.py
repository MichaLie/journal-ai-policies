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

    def test_missing_type_counts_as_publisher(self):
        entities = [self.entity(str(i), 'permitted') for i in range(4)]
        del entities[0]['type']
        self.assertEqual(self.compute_rows(entities)['n'], 4)


def make(axis, plain, permissions, group="extended", disclosure="not_addressed"):
    """Rows for one axis from (name, permission) pairs."""
    entities = [{"name": n, "type": "publisher",
                 "policies": [{"axis": axis, "permission": perm, "disclosure": disclosure}]}
                for n, perm in permissions]
    axes = {axis: {"title": plain, "group": group}}
    raw = {"activities": [], "extended_axes": [{"key": axis, "plain": plain}]}
    return compute(entities, axes, raw)["rows"][0]


class RuleWordingTests(unittest.TestCase):
    def test_due_process_has_its_own_sentence(self):
        row = make("due_process", "Knowing why you were flagged, and appealing",
                   [("A", "permitted_with_conditions"), ("B", "permitted_with_conditions"),
                    ("C", "permitted"), ("D", "not_addressed"), ("E", "not_addressed")])
        self.assertEqual(row["rule"], "At least one AI-specific safeguard (a review trigger, contact "
                                      "with the author, or an appeal route) is stated by 3 of the 5 assessed organisations")
        self.assertNotIn("permitted", row["rule"])

    def test_detection_screening_has_its_own_sentence(self):
        row = make("detection_screening", "Being screened by AI detectors",
                   [(str(i), "permitted") for i in range(4)] + [("Quiet", "not_addressed")])
        self.assertEqual(row["rule"],
                         "Screening of submissions (including with AI tools) is stated by 4 of the 5 assessed organisations")

    def test_override_never_applies_to_a_silent_axis(self):
        row = make("due_process", "Appeals", [(str(i), "not_addressed") for i in range(4)])
        self.assertEqual(row["band"], "void")
        self.assertIsNone(row["rule"])

    def test_other_axes_keep_the_generic_sentence(self):
        row = make("reviewer_use", "Reviewing", [(str(i), "permitted_with_conditions") for i in range(4)])
        self.assertEqual(row["rule"], "Reviewing is permitted under conditions")


class SilenceIsNotDissentTests(unittest.TestCase):
    def test_silent_organisations_are_listed_apart_from_exceptions(self):
        row = make("reviewer_use", "Reviewing",
                   [("A", "permitted"), ("B", "permitted"), ("C", "permitted"),
                    ("D", "permitted"), ("E", "permitted"), ("Forbids", "prohibited"),
                    ("Quiet", "not_addressed")])
        self.assertEqual(row["dissenters"], ["Forbids"])
        self.assertEqual(row["silent"], ["Quiet"])

    def test_discouraging_is_a_different_stance_from_forbidding(self):
        row = make("reviewer_use", "Reviewing",
                   [("A", "prohibited"), ("B", "prohibited"), ("C", "prohibited"),
                    ("Soft", "discouraged"), ("Quiet", "not_addressed")])
        self.assertEqual(row["dissenters"], ["Soft"])
        self.assertEqual(row["silent"], ["Quiet"])

    def test_silent_majority_names_the_ones_that_speak(self):
        row = make("reviewer_use", "Reviewing",
                   [("A", "not_addressed"), ("B", "not_addressed"), ("C", "not_addressed"),
                    ("Speaks", "permitted")])
        self.assertEqual(row["dissenters"], ["Speaks"])
        self.assertEqual(row["silent"], [])


class ThinBandTests(unittest.TestCase):
    def test_thin_band_states_no_rule(self):
        row = make("reviewer_use", "Reviewing", [("A", "prohibited"), ("B", "prohibited")])
        self.assertEqual(row["band"], "thin")
        self.assertIsNone(row["rule"])
        self.assertEqual(row["n"], 2)

    def test_thin_band_states_no_rule_even_for_an_override_axis(self):
        row = make("due_process", "Appeals", [("A", "permitted"), ("B", "not_addressed")])
        self.assertEqual(row["band"], "thin")
        self.assertIsNone(row["rule"])


if __name__ == "__main__":
    unittest.main()

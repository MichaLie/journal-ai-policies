"""validate.py must fail loudly when it cannot check, and flag records that
claim more than their sources can support. Synthetic records only."""
import contextlib
import copy
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import validate
import verify_quotes


def entity(**over):
    e = {"id": "sample", "name": "Sample", "type": "publisher", "policy_owner": "sample",
         "sources": [{"id": "policy", "url": "https://example.org/policy", "role": "policy",
                      "audience": "all", "status": "current", "authoritative": True,
                      "fetch_method": "http", "last_verified": "2026-10-15"}],
         "policies": [{"axis": "language_refinement", "permission": "permitted",
                       "disclosure": "not_required",
                       "evidence": [{"source": "policy", "quote": "Authors are responsible.",
                                     "quote_provenance": "raw_bytes"}]}],
         "_file": "sample.yml"}
    e.update(over)
    return e


class ValidateTests(unittest.TestCase):
    def run_validate(self, entities, quotes=lambda: []):
        out = io.StringIO()
        with patch.object(validate, "load_entities", lambda: copy.deepcopy(entities)), \
             patch.object(verify_quotes, "collect_unverified", quotes), \
             contextlib.redirect_stdout(out):
            code = validate.main()
        return code, out.getvalue()

    def test_clean_record_passes(self):
        code, out = self.run_validate([entity()])
        self.assertEqual(code, 0, out)
        self.assertIn("0 errors · 0 warnings", out)

    def test_quote_gate_that_cannot_run_is_an_error(self):
        def broken():
            raise RuntimeError("snapshot directory unreadable")
        code, out = self.run_validate([entity()], quotes=broken)
        self.assertEqual(code, 1)
        self.assertIn("ERROR quote verification could not run", out)

    def test_impossible_date_fails_schema(self):
        e = entity()
        e["sources"][0]["last_verified"] = "2026-13-45"
        code, out = self.run_validate([e])
        self.assertEqual(code, 1)
        self.assertIn("last_verified", out)

    def test_browser_source_must_be_quoted_as_browser_dom(self):
        e = entity()
        e["sources"][0]["fetch_method"] = "browser"
        code, out = self.run_validate([e])
        self.assertEqual(code, 0)                      # warning for now, not an error
        self.assertIn("should be browser_dom", out)

    def test_http_source_cannot_claim_browser_dom(self):
        e = entity()
        e["policies"][0]["evidence"][0]["quote_provenance"] = "browser_dom"
        code, out = self.run_validate([e])
        self.assertIn("claims provenance browser_dom", out)

    def test_unverified_and_relayed_quotes_are_allowed_anywhere(self):
        for prov in ("unverified", "summariser_relayed"):
            e = entity()
            e["sources"][0]["fetch_method"] = "browser"
            e["policies"][0]["evidence"][0]["quote_provenance"] = prov
            code, out = self.run_validate([e])
            self.assertNotIn("should be browser_dom", out)

    def test_authoritative_all_overlaps_a_specific_audience(self):
        e = entity()
        e["sources"].append({"id": "authors", "url": "https://example.org/authors", "role": "guidance",
                             "audience": "authors", "status": "current", "authoritative": True,
                             "fetch_method": "http", "last_verified": "2026-10-15"})
        code, out = self.run_validate([e])
        self.assertEqual(code, 0)
        self.assertIn("overlap", out)

    def test_distinct_audiences_do_not_overlap(self):
        e = entity()
        e["sources"][0]["audience"] = "reviewers"
        e["sources"].append({"id": "authors", "url": "https://example.org/authors", "role": "guidance",
                             "audience": "authors", "status": "current", "authoritative": True,
                             "fetch_method": "http", "last_verified": "2026-10-15"})
        code, out = self.run_validate([e])
        self.assertNotIn("overlap", out)

    def test_policy_owner_must_resolve(self):
        code, out = self.run_validate([entity(policy_owner="nobody")])
        self.assertIn("policy_owner 'nobody'", out)
        code, out = self.run_validate([entity(policy_owner="other"),
                                       entity(id="other", name="Other", _file="other.yml")])
        self.assertNotIn("policy_owner", out)


if __name__ == "__main__":
    unittest.main()

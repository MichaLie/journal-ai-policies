"""Failure-path regression tests. No publisher requests or GitHub writes."""
import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fetch
import diff


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.snapshots = Path(self.temp.name)
        self.day = datetime.date(2026, 10, 15)
        self.source = {"id": "policy", "url": "https://example.org/policy",
                       "fetch_method": "http", "last_verified": "2026-10-15",
                       "adjudicated_sha256": "a" * 64}
        self.entity = {"id": "sample", "name": "Sample", "sources": [self.source], "policies": []}
        self.folder = self.snapshots / "sample/policy"
        self.folder.mkdir(parents=True)
        self.good = b"<html><title>Editorial policy</title><p>Authors are responsible.</p></html>"
        self.source["adjudicated_sha256"] = fetch.drift_hash(self.good)
        (self.folder / "content.bin").write_bytes(self.good)
        (self.folder / "text.txt").write_text(fetch.visible_text(self.good))
        self.meta = {"url": self.source["url"], "fetched": self.day.isoformat(),
                     "sha256": fetch.sha256(self.good), "text_sha256": fetch.drift_hash(self.good)}
        (self.folder / "meta.json").write_text(json.dumps(self.meta))
        for module in (fetch, diff):
            for name, value in (("SNAPSHOTS", self.snapshots), ("today", lambda: self.day),
                                ("load_entities", lambda: [self.entity])):
                p = patch.object(module, name, value)
                p.start(); self.addCleanup(p.stop)

    def run_fetch(self, result):
        with patch.object(fetch, "fetch_url", return_value=result), contextlib.redirect_stdout(io.StringIO()):
            return fetch.main(["fetch.py"])

    def run_diff(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = diff.main()
        return code, json.loads((self.snapshots / "review-queue.json").read_text())

    def test_changed_text_is_queued_even_when_existing_quote_survives(self):
        changed = self.good.replace(b"</p>", b" New disclosure requirement.</p>")
        self.assertEqual(self.run_fetch((changed, "200", self.source["url"])), 0)
        code, queue = self.run_diff()
        self.assertEqual(code, 2)
        self.assertEqual(len(queue["review_queue"]), 1)
        self.assertIn("Authors are responsible.", (self.folder / "text.txt").read_text())
        # Fetching the same unreviewed change again must not make it disappear.
        self.run_fetch((changed, "200", self.source["url"]))
        self.assertEqual(self.run_diff()[0], 2)

    def test_failed_fetch_preserves_good_snapshot_and_is_not_unchanged_success(self):
        self.assertEqual(self.run_fetch((None, "HTTP 403", None)), 1)
        self.assertEqual((self.folder / "content.bin").read_bytes(), self.good)
        code, queue = self.run_diff()
        self.assertEqual(code, 2)
        self.assertEqual(queue["retrieval_failures"][0]["detail"], "HTTP 403")
        self.assertEqual(self.run_fetch((self.good, "200", self.source["url"])), 0)
        self.assertEqual(self.run_diff()[0], 0)

    def test_http_200_challenge_does_not_overwrite_evidence(self):
        challenge = b"<html><title>Client Challenge</title>Please enable JavaScript to proceed.</html>"
        self.assertEqual(self.run_fetch((challenge, "200", self.source["url"])), 1)
        self.assertEqual((self.folder / "content.bin").read_bytes(), self.good)
        self.assertEqual(json.loads((self.folder / "meta.json").read_text()), self.meta)
        code, queue = self.run_diff()
        self.assertEqual(code, 2)
        self.assertEqual(queue["retrieval_failures"][0]["detail"], "CHALLENGE PAGE")

    def test_archive_hash_cannot_substitute_for_a_live_read(self):
        self.source.update(fetch_method="archive", last_live_verified="2026-09-11",
                           live_url="https://example.org/current")
        with patch.object(fetch, "fetch_url") as network, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fetch.main(["fetch.py"]), 2)
            network.assert_not_called()
        code, queue = self.run_diff()
        self.assertEqual(code, 2)
        self.assertEqual(queue["live_review_due"][0]["url"], "https://example.org/current")
        self.source["last_live_verified"] = self.day.isoformat()
        self.assertEqual(self.run_diff()[0], 0)

    def test_browser_extract_is_retained_and_recheck_becomes_due(self):
        self.source["fetch_method"] = "browser"
        with patch.object(fetch, "fetch_url") as network, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fetch.main(["fetch.py"]), 0)
            network.assert_not_called()
        self.day = datetime.date(2026, 11, 1)
        code, queue = self.run_diff()
        self.assertEqual(code, 2)
        self.assertEqual(len(queue["live_review_due"]), 1)

    def test_missing_snapshot_and_missing_signoff_require_review(self):
        (self.folder / "meta.json").unlink()
        code, queue = self.run_diff()
        self.assertEqual(code, 2)
        self.assertEqual(queue["never_fetched"], ["sample/policy"])
        (self.folder / "meta.json").write_text(json.dumps(self.meta))
        self.source.pop("adjudicated_sha256")
        code, queue = self.run_diff()
        self.assertEqual(code, 2)
        self.assertEqual(queue["awaiting_first_signoff"], 1)

    def test_old_http_snapshot_requires_a_new_fetch(self):
        self.day = datetime.date(2026, 11, 1)
        code, queue = self.run_diff()
        self.assertEqual(code, 2)
        self.assertEqual(queue["retrieval_failures"][0]["status"], "stale_fetch")


class WorkflowTests(unittest.TestCase):
    def test_nonzero_pipeline_codes_reach_outputs_under_github_bash_flags(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/verify.yml").read_text())
        steps = {s.get("id"): s for s in workflow["jobs"]["monitor"]["steps"] if s.get("id")}
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "tools").mkdir()
            for step, tool, code in (("fetch", "fetch", 1), ("gate", "validate", 1), ("diff", "diff", 2)):
                (base / "tools" / f"{tool}.py").write_text(f"raise SystemExit({code})\n")
                output = base / f"{step}.output"
                # Run the real workflow block, with only log paths isolated.
                script = steps[step]["run"].replace("/tmp/", str(base) + "/")
                env = {**os.environ, "GITHUB_OUTPUT": str(output)}
                result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
                                        cwd=base, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.read_text().strip(), f"code={code}")

    def test_final_monitor_status_is_red_for_any_incomplete_check(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/verify.yml").read_text())
        final = workflow["jobs"]["monitor"]["steps"][-1]
        self.assertEqual(final["if"], "always()")
        for codes, expected in ((("0", "0", "0"), 0), (("1", "0", "0"), 1),
                                (("0", "1", "0"), 1), (("0", "0", "2"), 1), (("", "0", "0"), 1)):
            env = {**os.environ, **dict(zip(("FETCH_CODE", "GATE_CODE", "DIFF_CODE"), codes))}
            result = subprocess.run(["bash", "-c", final["run"]], env=env)
            self.assertEqual(result.returncode, expected)


if __name__ == "__main__":
    unittest.main()

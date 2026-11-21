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

    def quote(self, text):
        self.entity["policies"] = [{"axis": "language_refinement", "permission": "permitted",
                                    "disclosure": "not_required",
                                    "evidence": [{"source": "policy", "quote": text,
                                                  "quote_provenance": "raw_bytes"}]}]

    def assert_evidence_kept(self):
        self.assertEqual((self.folder / "content.bin").read_bytes(), self.good)
        self.assertEqual((self.folder / "text.txt").read_text(), fetch.visible_text(self.good))
        self.assertEqual(json.loads((self.folder / "meta.json").read_text()), self.meta)

    def test_shrunken_extract_is_suspect_and_not_stored(self):
        long_page = (b"<html><title>Editorial policy</title><p>Authors are responsible. "
                     + b"Further policy wording. " * 40 + b"</p></html>")
        self.good = long_page
        (self.folder / "content.bin").write_bytes(long_page)
        (self.folder / "text.txt").write_text(fetch.visible_text(long_page))
        self.meta["text_sha256"] = fetch.drift_hash(long_page)
        (self.folder / "meta.json").write_text(json.dumps(self.meta))
        stub = b"<html><title>Editorial policy</title><p>Please sign in to continue.</p></html>"
        self.assertEqual(self.run_fetch((stub, "200", self.source["url"])), 1)
        self.assert_evidence_kept()
        attempt = json.loads((self.folder / "attempt.json").read_text())
        self.assertEqual(attempt["status"], "failed")
        self.assertTrue(attempt["detail"].startswith("suspect extract: text shrank"))
        code, queue = self.run_diff()
        self.assertEqual(code, 2)
        self.assertTrue(queue["retrieval_failures"][0]["detail"].startswith("suspect extract"))

    def test_lost_quote_is_suspect_and_not_stored(self):
        self.quote("Authors are responsible.")
        same_size = self.good.replace(b"Authors are responsible.", b"Readers are welcome here.")
        self.assertEqual(self.run_fetch((same_size, "200", self.source["url"])), 1)
        self.assert_evidence_kept()
        detail = json.loads((self.folder / "attempt.json").read_text())["detail"]
        self.assertIn("suspect extract: 1 quoted passage(s)", detail)
        self.assertNotIn("redirected", detail)

    def test_quote_survives_normalisation_differences(self):
        self.quote("authors   are RESPONSIBLE.")
        changed = self.good.replace(b"</p>", b" New disclosure requirement.</p>")
        self.assertEqual(self.run_fetch((changed, "200", self.source["url"])), 0)
        self.assertIn("New disclosure requirement.", (self.folder / "text.txt").read_text())

    def test_quote_never_in_old_extract_does_not_block(self):
        self.quote("A sentence the stored extract never held.")
        changed = self.good.replace(b"</p>", b" New disclosure requirement.</p>")
        self.assertEqual(self.run_fetch((changed, "200", self.source["url"])), 0)

    def test_suspect_redirect_is_named(self):
        self.quote("Authors are responsible.")
        login = self.good.replace(b"Authors are responsible.", b"Log in to your account now.")
        self.assertEqual(self.run_fetch((login, "200", "https://example.org/login?next=policy")), 1)
        detail = json.loads((self.folder / "attempt.json").read_text())["detail"]
        self.assertIn("redirected to https://example.org/login", detail)
        self.assert_evidence_kept()

    def test_redirect_alone_is_not_suspect(self):
        self.quote("Authors are responsible.")
        self.assertEqual(self.run_fetch((self.good, "200", "https://example.org/policy/")), 0)
        self.assertEqual(json.loads((self.folder / "attempt.json").read_text())["status"], "fetched")
        self.assertFalse(fetch.moved_path("https://example.org/policy", "https://example.org/policy/"))
        self.assertTrue(fetch.moved_path("https://example.org/policy", "https://example.org/login"))

    def test_accept_suspect_stores_a_reviewed_change(self):
        self.quote("Authors are responsible.")
        reworded = self.good.replace(b"Authors are responsible.", b"Authors remain accountable.")
        with patch.object(fetch, "fetch_url", return_value=(reworded, "200", self.source["url"])), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fetch.main(["fetch.py", "--accept-suspect"]), 0)
        self.assertIn("Authors remain accountable.", (self.folder / "text.txt").read_text())

    def test_first_fetch_has_nothing_to_compare(self):
        for name in ("text.txt", "meta.json", "content.bin"):
            (self.folder / name).unlink()
        self.quote("Authors are responsible.")
        self.assertEqual(self.run_fetch((self.good, "200", self.source["url"])), 0)
        self.assertTrue((self.folder / "text.txt").exists())

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

    def monitor_steps(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/verify.yml").read_text())
        return workflow["jobs"]["monitor"]["steps"]

    def test_failed_gate_persists_nothing(self):
        persist = next(s for s in self.monitor_steps() if s.get("name") == "Persist the hash chain")
        self.assertEqual(persist.get("if"), "steps.gate.outputs.code == '0'")

    def test_review_issue_runs_after_earlier_failures(self):
        issue = next(s for s in self.monitor_steps() if "review issue" in s.get("name", ""))
        self.assertTrue(issue["if"].replace(" ", "").startswith("always()&&("), issue["if"])

    def run_issue_step(self, open_issue):
        """Run the real issue script against a fake `gh` that logs its calls."""
        issue = next(s for s in self.monitor_steps() if "review issue" in s.get("name", ""))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "bin").mkdir()
            log = base / "gh.log"
            gh = base / "bin" / "gh"
            gh.write_text("#!/bin/bash\n"
                          f'echo "$*" >> "{log}"\n'
                          'if [ "$1 $2" = "issue list" ]; then echo "${FAKE_OPEN_ISSUE}"; fi\n')
            gh.chmod(0o755)
            (base / "gate.txt").write_text("ERROR quote missing\n")
            script = issue["run"].replace("/tmp/", str(base) + "/")
            env = {**os.environ, "PATH": f"{base / 'bin'}:{os.environ['PATH']}",
                   "FAKE_OPEN_ISSUE": open_issue, "GATE_CODE": "1"}
            result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
                                    cwd=base, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            body = (base / "issue.md").read_text()
            return log.read_text().splitlines(), body

    def test_open_review_issue_gets_a_comment_not_a_duplicate(self):
        calls, body = self.run_issue_step("42")
        self.assertTrue(any(c.startswith("issue comment 42") for c in calls), calls)
        self.assertFalse(any(c.startswith("issue create") for c in calls), calls)
        self.assertIn("nothing from this run was committed", body)
        self.assertIn("(no fetch output)", body)

    def test_no_open_review_issue_creates_one(self):
        calls, _ = self.run_issue_step("")
        self.assertTrue(any(c.startswith("issue create") for c in calls), calls)
        self.assertFalse(any(c.startswith("issue comment") for c in calls), calls)


if __name__ == "__main__":
    unittest.main()

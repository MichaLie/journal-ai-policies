"""The rendered page must say only what stays true after the build day.
Builds into a temporary directory; docs/ is never touched."""
import contextlib
import io
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build


def policy(axis, permission, disclosure="required", where=("acknowledgements",)):
    return {"axis": axis, "permission": permission, "disclosure": disclosure,
            "disclosure_location": list(where)}


class WhereItGoesTests(unittest.TestCase):
    def test_prohibiting_organisation_is_not_a_place_to_declare(self):
        entities = [{"name": "Allows", "type": "publisher", "policies": [policy("writing_drafting", "permitted")]},
                    {"name": "Forbids", "type": "publisher", "policies": [policy("writing_drafting", "prohibited")]}]
        self.assertEqual(build.where_it_goes("writing_drafting", entities),
                         [("acknowledgements", ["Allows"])])

    def test_same_population_as_the_consensus_panel(self):
        entities = [{"name": "Untyped", "policies": [policy("writing_drafting", "permitted")]},
                    {"name": "Journal", "type": "journal", "policies": [policy("writing_drafting", "permitted")]},
                    {"name": "Funder", "type": "funder", "policies": [policy("writing_drafting", "permitted")]},
                    {"name": "Taxonomy", "type": "publisher", "policy_architecture": "classification_only",
                     "policies": [policy("writing_drafting", "permitted")]}]
        self.assertEqual(build.where_it_goes("writing_drafting", entities),
                         [("acknowledgements", ["Journal", "Untyped"])])


class OpeningCountsTests(unittest.TestCase):
    """The first sentence a reader sees counts only organisations ASSESSED on
    writing: an entity with no writing_drafting record has not been checked,
    so it must not be counted as one that "does not ban"."""

    def base(self):
        return [{"name": "Allows", "type": "publisher", "policies": [policy("writing_drafting", "permitted")]},
                {"name": "Conditional", "type": "journal",
                 "policies": [policy("writing_drafting", "permitted_with_conditions")]},
                {"name": "Unchecked", "type": "publisher", "policies": [policy("passing_off", "prohibited")]},
                {"name": "Funder", "type": "funder", "policies": [policy("writing_drafting", "prohibited")]}]

    def test_denominator_is_assessed_publishers_only(self):
        text = build.opening_counts(self.base())
        self.assertIn("Of the 2 publishers and journals assessed here on manuscript writing", text)
        self.assertIn("2 allow it under conditions", text)

    def test_no_ban_claim_only_without_a_prohibited_cell(self):
        self.assertIn("none imposes a blanket ban", build.opening_counts(self.base()))

    def test_a_ban_switches_to_a_count(self):
        ents = self.base() + [{"name": "Bans", "type": "publisher",
                               "policies": [policy("writing_drafting", "prohibited")]}]
        text = build.opening_counts(ents)
        self.assertNotIn("none imposes", text)
        self.assertIn("Of the 3 publishers and journals assessed here on manuscript writing, "
                      "1 ban AI-assisted drafting", text)


class FirstSentenceTests(unittest.TestCase):
    def test_stops_at_the_first_full_stop(self):
        self.assertEqual(build.first_sentence("Allowed for language. Must be declared."),
                         ("Allowed for language.", True))

    def test_abbreviations_do_not_end_a_sentence(self):
        head, more = build.first_sentence("Tools (e.g. ChatGPT) are allowed. Declare them.")
        self.assertEqual(head, "Tools (e.g. ChatGPT) are allowed.")
        self.assertTrue(more)

    def test_single_sentence_reports_nothing_more(self):
        self.assertEqual(build.first_sentence("Declare it in the methods."),
                         ("Declare it in the methods.", False))


class SourceLabelTests(unittest.TestCase):
    def test_domain_and_label(self):
        s = {"url": "https://www.elsevier.com/about/policies", "role": "announcement", "audience": "all"}
        self.assertEqual(build.source_label(s), "elsevier.com · Announcement")
        s.update(authoritative=True, audience="reviewers")
        self.assertEqual(build.source_label(s), "elsevier.com · Policy page for reviewers")


class RenderedPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with patch.object(build, "DOCS", Path(cls.tmp.name)), contextlib.redirect_stdout(io.StringIO()):
            build.build()
        cls.page = (Path(cls.tmp.name) / "index.html").read_text(encoding="utf-8")
        cls.entities = build.load_entities()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_freshness_is_a_date_not_an_age(self):
        self.assertNotRegex(self.page, r"checked \d+d ago")
        self.assertNotIn("days ago", self.page)
        self.assertRegex(self.page, r'class="f \w+">checked \d{4}-\d{2}-\d{2}<')

    def test_every_record_has_a_stable_anchor(self):
        for e in self.entities:
            self.assertIn(f'<details class="ent-card" id="{e["id"]}">', self.page)

    def test_legend_names_discouraged(self):
        legend = re.search(r'<div class="legend".*?</div>', self.page, re.S).group(0)
        self.assertIn("discouraged", legend)

    def test_header_says_stored_copy(self):
        self.assertIn("checked against the stored copy of the page they came from</span>", self.page)

    def test_fixed_copy(self):
        self.assertNotIn("need write nothing", self.page)
        self.assertNotRegex(self.page, r"\b1 use a saved excerpt|\b([02-9]|\d\d+) uses a saved excerpt")
        self.assertNotRegex(self.page, r"\d+ of \d+ organisations recorded here so far")

    def test_filter_bars_are_progressive_enhancement(self):
        # One above the grid, one above the records; hidden until the script runs.
        self.assertEqual(self.page.count('<div class="filter" data-filter hidden>'), 2)
        for scope in ("grid", "records"):
            self.assertIn(f'<input type="search" id="q-{scope}"', self.page)
            self.assertIn(f'<label class="vh" for="q-{scope}">', self.page)
        self.assertIn('placeholder="Find a publisher, journal or funder&hellip;"', self.page)
        self.assertIn('id="filter-live" class="vh" role="status" aria-live="polite"', self.page)
        self.assertIn("<script>", self.page)
        self.assertNotRegex(self.page, r"<script[^>]+src=")

    def test_filter_counts_are_computed_from_types(self):
        self.assertEqual(self.page.count(f'All<span class="fn">{len(self.entities)}</span>'), 2)
        counts = {}
        for e in self.entities:
            counts[build.group_of(e)] = counts.get(build.group_of(e), 0) + 1
        self.assertNotIn("other", counts, "every entity type must belong to a filter group")
        for key, label, _ in build.GROUPS:
            if counts.get(key):
                btn = (f'data-g="{key}" aria-pressed="false">{build.esc(label)}'
                       f'<span class="fn">{counts[key]}</span>')
                self.assertEqual(self.page.count(btn), 2, key)

    def test_grid_has_sticky_header_in_a_bounded_box(self):
        self.assertRegex(build.CSS, r"\.tw\{[^}]*overflow:auto;max-height:")
        self.assertRegex(build.CSS, r"\.matrix thead th\{[^}]*position:sticky;top:0")
        self.assertIn("min-width:min(11rem,42vw)", build.CSS)
        # The visible caption sits outside the scroll box; the table keeps one for screen readers.
        self.assertRegex(self.page, r'<p class="tcap" aria-hidden="true">[^<]+</p>'
                                    r'<div class="tw" tabindex="0" role="region"')
        self.assertIn('<caption class="vh">', self.page)

    def test_grid_headers_link_to_records(self):
        for e in self.entities:
            self.assertRegex(self.page, rf'<th class="ent" scope="col" data-g="\w+" data-q="[^"]*">'
                                        rf'<a href="#{re.escape(e["id"])}">')

    def test_every_card_has_a_summary_strip(self):
        self.assertEqual(self.page.count('<p class="vsum">'), len(self.entities))
        quoted = sum(1 for e in self.entities for p in e.get("policies", []) if p.get("evidence"))
        self.assertEqual(self.page.count('<span class="verdict">'), quoted)

    def test_every_card_with_policies_opens_on_a_rules_table(self):
        with_pol = [e for e in self.entities if e.get("policies")]
        self.assertEqual(self.page.count('<table class="rt" role="table">'), len(with_pol))
        for e in with_pol:
            card = re.search(rf'<details class="ent-card" id="{re.escape(e["id"])}">(.*?)</details>\n',
                             self.page, re.S).group(1)
            body = card.split('<div class="ent-body">', 1)[1]
            # The table comes before notes, sources and quotes.
            self.assertLess(body.index('<table class="rt"'), body.index("<h3>Cite this</h3>"), e["id"])
            rows = re.search(r'<table class="rt".*?</table>', body, re.S).group(0)
            self.assertEqual(rows.count('<tr role="row"><th scope="row"'), len(e["policies"]), e["id"])
            if any(p.get("evidence") for p in e["policies"]):
                self.assertLess(body.index('<table class="rt"'), body.index('<details class="q">'), e["id"])

    def test_card_headers_carry_no_internal_tags(self):
        for summary in re.findall(r'<details class="ent-card" id="[^"]+"><summary>(.*?)</summary>',
                                  self.page, re.S):
            self.assertNotIn('class="tag arch"', summary)
            for v in ("rule_with_exemptions", "rule with exemptions", "prose", ">http<", ">all<"):
                self.assertNotIn(v, summary.lower())

    def test_source_links_show_a_domain_not_a_raw_url(self):
        self.assertNotRegex(self.page, r'<a href="https?://[^"]+"[^>]*>https?://')
        self.assertIn("Other page", self.page)
        self.assertNotIn("Also held, but not the one to cite", self.page)
        self.assertRegex(self.page, r'<a href="https?://[^"]+" title="https?://[^"]+">[a-z0-9.-]+ · Policy page')

    def test_consensus_detail_lines_are_not_monospace_capitals(self):
        caps = set()
        for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", build.CSS):
            if "text-transform:uppercase" in body:
                caps |= set(re.findall(r"\.([\w-]+)", sel))
        summary = self.page.split('<section id="summary"', 1)[1].split("</section>", 1)[0]
        lines = re.findall(r'<p class="rule-detail">(.*?)</p>', summary, re.S)
        self.assertTrue(lines)
        self.assertNotIn("rule-detail", caps)
        self.assertNotIn("rule-txt", caps)
        for line in lines:
            for cls in re.findall(r'class="([^"]+)"', line):
                self.assertFalse(set(cls.split()) & caps, f"caps label inside a detail line: {cls}")
        # No band boxes: the bands carry no border of their own.
        band = re.search(r"\.band\{([^}]*)\}", build.CSS).group(1)
        self.assertNotIn("border", band)

    def test_zero_counters_are_hidden(self):
        self.assertNotRegex(self.page, r"\b0 (cells|remain|quotes? still needed|recorded verdicts?)")
        n_gaps = sum(1 for e in self.entities for p in e.get("policies", [])
                     if p["permission"] != "not_addressed" and not p.get("evidence"))
        if n_gaps == 0:
            self.assertNotIn("still await", self.page)
            self.assertNotIn("published rather than hidden", self.page)

    def test_no_pipeline_self_talk(self):
        for phrase in ("in this build", "never written by hand", "Rows move between groups on their own",
                       "Also held, but not the one to cite"):
            self.assertNotIn(phrase.lower(), self.page.lower())
        self.assertIn("nothing here is written by hand", self.page)

    def test_lookup_sits_under_the_header_and_is_hidden_without_js(self):
        self.assertRegex(self.page, r'</header>\n<form class="lookup" data-lookup hidden role="search"')
        self.assertIn('<label class="vh" for="q-top">', self.page)
        self.assertIn('placeholder="Jump to a journal, publisher or funder&hellip;"', self.page)
        self.assertLess(self.page.index('data-lookup'), self.page.index('<nav class="toc"'))
        # It reuses the records filter: the script hands its query to q-records.
        self.assertIn("querySelector('[data-lookup]')", build.JS)
        self.assertIn("getElementById('q-records')", build.JS)

    def test_copy_buttons_are_progressive_enhancement(self):
        n_tmpl = self.page.count('<blockquote class="tmpl-text">')
        self.assertTrue(n_tmpl)
        self.assertEqual(self.page.count('class="copy" data-copy hidden'), n_tmpl)
        self.assertIn("[data-copy]", build.JS)

    def test_print_opens_every_details(self):
        self.assertIn("beforeprint", build.JS)
        self.assertRegex(build.CSS, r"@media print\{[^@]*details>\*\{display:block!important\}")

    def test_advice_names_link_to_records(self):
        ids = {e["id"] for e in self.entities}
        for cls in ("lane-who", "loc-who"):
            spans = re.findall(rf'<span class="{cls}">(.*?)</span>', self.page)
            self.assertTrue(spans, cls)
            for s in spans:
                for target in re.findall(r'href="#([^"]+)"', s):
                    self.assertIn(target, ids)
                self.assertNotRegex(re.sub(r"<a [^>]*>.*?</a>", "", s), r"\w", f"unlinked name in {cls}")


if __name__ == "__main__":
    unittest.main()

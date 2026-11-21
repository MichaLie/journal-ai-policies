# What journals actually require

A version-controlled record of what publishers, journals, funders, preprint servers and
research-ethics bodies say about generative AI in the natural and life sciences.

- **Site:** <https://michalie.github.io/journal-ai-policies/>
- **Data:** <https://michalie.github.io/journal-ai-policies/data.json> (CC0)
- **Corrections:** [open an issue](https://github.com/MichaLie/journal-ai-policies/issues)
- **Related:** [Publishing Under AI](https://michalie.github.io/publishing-under-ai/): how scientific writing and peer review are coping with AI, where researchers disagree, and what is being tried · [Agent Risk Atlas](https://michalie.github.io/agent-risk-atlas/): how research with AI agents goes wrong, and what protects you.

Maintained by [MichaLie](https://github.com/MichaLie). If you work for an organisation recorded
here and think a record is wrong, open an issue. Every record names its source and quotes the
wording it relies on, so corrections can be specific.

Policies can change between checks. Direct sources are re-fetched on a schedule; browser and
archive-backed sources are queued for a dated live read. The git history of `data/entities/` is the dataset.

Currently 47 organisations, 1,549 quotes, 69 sources. Every source re-read and every record
re-checked on 20 November 2026. The agreement panel counts publishers and journals only; funders,
preprint servers and advisory bodies appear in the grid and records but are not counted.
See [the 20 November review notes](reviews/2026-11-20.md) for what was checked and what is still
open, and [how quotes become cell values](schema/coding-conventions.md) for the coding rules.

## Install

Python 3.11+.

```bash
pip install pyyaml jsonschema pypdf
```

## Commands

```bash
python3 tools/validate.py       # schema, cross-references, every quote re-checked
python3 tools/fetch.py          # fetch HTTP sources; queue sources needing a live read
python3 tools/diff.py           # what changed since last sign-off (exit 2 = review needed)
python3 tools/build.py          # render docs/
python3 tools/verify_quotes.py  # quote report on its own
python3 -m unittest discover -s tests -v  # regression tests
```

`validate.py` must pass before anything ships. It fails the build if a quote cannot be found in the
stored copy of its source.

`fetch.py` exits 1 for retrieval failures and 2 for outstanding manual live checks. Failed requests,
empty extracts and recognised HTTP-200 challenge pages leave the last good snapshot intact and write
an `attempt.json` receipt. `diff.py` includes those failures, missing snapshots, unsigned sources and
outstanding live checks in its review queue. An unchanged stored hash is not proof of a successful
current retrieval. The scheduled workflow records all exit codes, opens a review issue when needed,
and finishes with a failing status while review or repair remains outstanding.

Fixed archive captures are retained as historical evidence, not fetched again to claim live freshness.
Read their confirmed `live_url` and update `last_live_verified` only after checking the current text.
Browser/manual sources use `last_verified` for the same purpose. Each monitoring run requires a live
check dated that day, so the 22 browser and archive sources need a same-day live read on every run. In
practice the monthly monitor therefore ends red and adds its report to the open review issue; treat
that issue as the to-do list. To retain a new
browser excerpt, save its text and scope in its own snapshot directory, label its provenance
`browser_dom`, and review its new text hash before updating the record. The monitor never signs it off.

If a fetch returns an extract that is much shorter than the stored one, or that no longer contains a
quote the records cite, `fetch.py` keeps the stored copy and reports the source as suspect. After
reading the live page yourself, `python3 tools/fetch.py <entity> --accept-suspect` stores the new copy.

## Layout

```
schema/stm-activities.yml     the nine STM activities (verbatim) plus 7 extended axes (our wording)
schema/coding-conventions.md  how a quote becomes a cell value
schema/entity.schema.json     record structure and controlled vocabularies
schema/reader-guidance.yml    reader-facing copy, kept separate from the verbatim STM file
data/entities/*.yml           one file per organisation
snapshots/<entity>/<source>/  fetched bytes, hashes and history
tools/common.py               paths, freshness thresholds, staleness tombstone
tools/fetch.py                fetch, hash, snapshot
tools/diff.py                 compare against last sign-off, emit review queue
tools/verify_quotes.py        check quotes against stored bytes
tools/consensus.py            derive what holds, what's contested, what's unanswered
tools/validate.py             schema, cross-references, quote check
tools/build.py                render docs/
tests/                        regression tests for monitoring, validation, consensus and build
reviews/                      dated audit notes
```

Each tool's docstring explains why it works the way it does.

## Editing records

1. Quote policy text; don't paraphrase it.
2. `raw_bytes` provenance is enforced. The quote must be findable in the stored source text.
   `browser_dom` is a directly captured, labelled browser extract; it is checked against that extract,
   not presented as a raw HTTP response or a full-page snapshot.
   `summariser_relayed` carries paraphrase risk. `unverified` ships labelled.
3. Don't guess URLs. If you didn't load it: `url: null`, `status: unconfirmed`.
4. `not_addressed` means we checked and found nothing. Omitting the axis means we haven't checked.
   These render differently; don't substitute one for the other.
5. A changed hash opens a review item. A person re-reads the source and updates
   `adjudicated_sha256`. Don't automate that.
6. Don't hand-write the summary. If a headline claim looks wrong, fix the records.
7. Editorial wording goes in `reader-guidance.yml`, not `stm-activities.yml`. Empirical claims
   there need a citation key.
8. Substantive contradictions go in `coherence`, both sides quoted and linked. Dating and tagging
   oddities go in `metadata_inconsistency` and aren't counted as contradictions.

## Limitations

- Records published policy, not practice.
- Coverage is activity-specific; blank cells are unassessed, not silent.
- Browser excerpts are labelled and archived separately from HTTP captures.
- Sources without an `adjudicated_sha256` have not yet been signed off by the maintainer.
- GitHub disables scheduled workflows after 60 days without repository activity. If nobody pushes,
  the monitor stops.

## Licence

Records CC0, chosen so the data can be taken over by someone else if this stops being maintained.
Code MIT. Quoted policy text belongs to the publishers and is reproduced as short excerpts for
comparison and criticism, with attribution and a link to the source. `snapshots/` holds the extracted
text of each policy page so that every quote can be re-checked; that text also belongs to the
publishers and is kept for verification.

## How to cite

Cite the dataset with the date of the version you used, for example:
MichaLie (2026). *What journals actually require* [dataset], version of 20 November 2026.
https://github.com/MichaLie/journal-ai-policies

## Corrections

See [CONTRIBUTING.md](CONTRIBUTING.md). Every record names its source and quotes the wording it relies
on, so a correction can point at a specific quote.

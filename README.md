# What journals actually require

A version-controlled record of what publishers and research-ethics bodies say about generative AI
in the natural and life sciences.

- **Site:** <https://michalie.github.io/journal-ai-policies/>
- **Data:** <https://michalie.github.io/journal-ai-policies/data.json> (CC0)
- **Background:** [`orientation.html`](orientation.html)
- **Corrections:** [open an issue](https://github.com/MichaLie/journal-ai-policies/issues)

Maintained by [MichaLie](https://github.com/MichaLie). If you work for an organisation recorded
here and think a record is wrong, open an issue. Every record names its source and quotes the
wording it relies on, so corrections can be specific.

Policies here change without announcement, so the record is re-fetched on a schedule and every
change is diffed. The git history of `data/entities/` is the dataset.

Currently 10 organisations, 50 quotes, 16 sources.

## Install

Python 3.11+.

```bash
pip install pyyaml jsonschema pypdf
```

## Commands

```bash
python3 tools/validate.py       # schema, cross-references, every quote re-checked
python3 tools/fetch.py          # fetch, hash and snapshot every source
python3 tools/diff.py           # what changed since last sign-off (exit 2 = review needed)
python3 tools/build.py          # render docs/
python3 tools/verify_quotes.py  # quote report on its own
```

`validate.py` must pass before anything ships. It fails the build if a quote cannot be found in the
stored copy of its source.

## Layout

```
schema/stm-activities.yml     the nine STM activities plus 7 extended axes, verbatim
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
```

Each tool's docstring explains why it works the way it does.

## Editing records

1. Quote policy text; don't paraphrase it.
2. `raw_bytes` provenance is enforced. The quote must be findable in bytes we hold.
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
- 10 organisations, nine Anglophone. No journal-level records, funders, preprint servers or content
  licensing yet.
- 3 of 16 sources block automated clients and are checked against dated Internet Archive captures.
  Each record says so.
- 1 substantive internal contradiction and 2 dating oddities across the ten organisations.
- GitHub disables scheduled workflows after 60 days without repository activity. If nobody pushes,
  the monitor stops.

## Licence

Records CC0, chosen so the data can be taken over by someone else if this stops being maintained.
Code MIT. Quoted policy text belongs to the publishers and is reproduced as short excerpts for
comparison and criticism, with attribution and a link to the source.

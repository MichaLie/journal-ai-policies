# Life-science AI-use policy observatory — working notes

Read this before touching `data/entities/`. The rules below are not style preferences;
each one exists because a comparable registry failed without it.

## What this repo is

A **time series**, not a table. The git history of `data/entities/` is the dataset.
It cannot be reconstructed after the fact — which is why records go in even when
incomplete, marked as incomplete, rather than waiting until they are perfect.

## The five hard rules

1. **Verbatim or nothing.** Never paraphrase policy text into a record. A quote gets
   the exact words, the source id, and nothing else. Accuracy of quotation is this
   project's only asset.

2. **`quote_provenance` is mandatory and meaningful.**
   `raw_bytes` — you extracted it from the fetched document yourself.
   `summariser_relayed` — it passed through a summarising fetch layer, so it carries
   paraphrase risk and must be re-checked before anyone cites it.
   `unverified` — you have the claim but not the document. Ships marked, never silently.

3. **Never construct a URL by pattern.** If you did not load it, `url: null` and
   `status: unconfirmed`. `tools/validate.py` enforces this. During scoping, a
   plausible-looking URL and a fabricated $23m licensing deal both traced back to a
   content farm impersonating a defunct standards body.

4. **Silence is a value.** `not_addressed` means *we checked and they say nothing*.
   Omitting the axis entirely means *we have not checked*. These are different claims
   and the site renders them differently. Never use one to mean the other.

5. **The diff engine never edits a record.** A changed hash opens a review item.
   A human re-reads the source and updates the quote, then updates `adjudicated_sha256`.
   If that ever becomes automated, the dataset stops being worth more than a scrape.

6. **Never claim `raw_bytes` without bytes.** `validate.py` re-checks every quote against
   the stored copy of its source and fails the build if one is missing or attributed to a
   page that does not contain it. An audit found one quote that was a paraphrase in
   quotation marks and eight attributed to the wrong page. The check is not optional and
   must not be weakened to make a record pass — fix the record.

7. **A stale title tag is not a self-contradiction.** Substantive contradictions go in
   `coherence` and need both sides quoted AND linked. Dating and tagging oddities go in
   `metadata_inconsistency` and are never counted as contradictions. Publicly labelling a
   Crossref deposit timestamp a publisher's self-contradiction is indefensible.

8. **Never hand-write the summary panel.** It is computed by `tools/consensus.py` from the
   records. If a headline claim is wrong, the records are wrong — fix those. Banding is on
   *stance* (allows/forbids/silent), so differing on conditions is not counted as disagreement,
   and any axis with fewer than 4 assessed entities is declared too thin to call rather than
   reported as a rule.

9. **Keep our voice out of `schema/stm-activities.yml`.** That file holds verbatim STM text.
   All reader-facing wording belongs in `schema/reader-guidance.yml`, and the site labels which
   is which. Mixing computed findings with editorial judgement unlabelled is how a resource
   quietly starts asserting more than it knows.

10. **Coverage numbers on a case card are provenance, not a claim.** "2 of 10 entities recorded
   here so far" is a fact about the build. Do not phrase it as "too few to generalise" there —
   that language belongs in the consensus panel, which is making a statistical claim. On an
   advice card it just teaches a frightened reader to distrust guidance that is sound.

## Adding an entity

- `id` is kebab-case and stable forever — it is the join key across the time series.
- `platform` ≠ `policy_owner`. EMBO Press sits on Springer Nature Link and sets its own
  policy; conflating them invents an inheritance that does not exist.
- `delegates_to_journal: true` **only** where journals genuinely deviate. Verified true
  for OUP and CUP; false for every other publisher checked. Do not set it speculatively —
  it multiplies the maintenance surface by the number of journals.
- Exactly one `authoritative: true` source per audience. That flag powers "cite this,
  not that", which is the feature authors actually need.
- Record `coherence` entries whenever an entity's own sources disagree. Seven entities
  already do. This is the headline finding, not a defect to tidy away.

## Fetching

`tools/fetch.py` writes each source to `snapshots/<entity>/<source>/` and nowhere else.
Do not add a shared temp directory. During scoping, one agent's generically-named temp
file was silently overwritten by another agent fetching into a shared directory, yielding
correctly-labelled output containing unrelated content. The failure is invisible because
the output still looks plausible.

Sources marked `browser`, `archive` or `manual` appear in a printed work queue. Never
"fix" this by dropping them — a monitor that silently skips a third of its sources
reports false confidence.

## What this does not have yet

- Journal-level records under OUP and CUP (the only two publishers verified to delegate).
- Funders (DFG, ERC, NWO, NIH), preprint servers, and the content-licensing axis.
- Cell Press, SAGE, Frontiers, MDPI, Taylor & Francis — all recorded in the reconnaissance,
  none yet a record here. Note that four of them appear in earlier drafts of the
  contradiction list; they must not be cited until they are actual records.
- Roughly half the possible organisation×axis cells. The rest render as `—`, which means
  *not assessed*, never *silent*.

## Fetching notes

A plain User-Agent gets 403 from Wiley, Springer Nature, science.org and COPE. Those sites
block obviously-scripted clients, not automation as such; presenting normal browser headers
recovered three sources previously recorded as permanently unreachable. Two still serve a
challenge page **with HTTP 200** — a 3KB body that hashes and stores perfectly while
containing no policy at all. That is why `fetch.py` stores a text hash and why quotes are
re-checked: a 200 is not evidence of content.

Three sources are PDFs. `fetch.py` extracts their text with pypdf (the first version decoded
them as UTF-8 and committed raw bytes as "text", which broke the quote gate on 2026-09-01) and
hashes the raw bytes for drift, because pypdf's extraction differs between versions. The three
archive-checked sources carry the Wayback toolbar, whose capture count changes whenever anyone
saves the page; `fetch.py` strips it before hashing. Live pages of all three were re-read in a
real browser on 2026-09-11 and every recorded quote was present verbatim.

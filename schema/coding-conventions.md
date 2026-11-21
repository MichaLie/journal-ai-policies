# How quotes become cell values

Every cell in the grid is coded from quoted policy text. This page states the rules used to turn a
quote into the values `permission`, `disclosure`, `disclosure_location` and `rationale`. They were
written down during the November 2026 audit and applied to every record. If a record departs from
them, the record is wrong; please open an issue.

Field vocabularies are defined in `entity.schema.json`. Activity definitions are in
`stm-activities.yml`.

## Evidence

- Quotes are copied byte for byte from the stored text of the source (`snapshots/<entity>/<source>/text.txt`).
  `tools/verify_quotes.py` checks every quote against that text.
- A condition or note may only state what a quote on the same activity, or the stored text, supports.
  No dates, counts or comparisons with other organisations unless the stored source says them.
- A record describes one organisation's own sources. A journal record with a parent publisher says
  what the journal's own pages say; the parent's policy is in the parent's record.

## Permission

| Source says | Coded as |
|---|---|
| The use is allowed, with no conditions | `permitted` |
| The use is allowed under stated conditions | `permitted_with_conditions` |
| The use is allowed only within a fixed, named limit ("except for language improvement", "only with approved tools") | `permitted_with_conditions`, limit in conditions |
| "Should only / primarily be used to …", "is discouraged" | `discouraged` |
| The use is banned, with no exception or only case-by-case permission (e.g. editor approval) | `prohibited`, exception in conditions |
| The whole source was read and says nothing on this activity | `not_addressed` |
| Not assessed | the activity is omitted; the grid shows `—` |

`not_addressed` and an omitted activity are different claims. The first means "we read it and it is
silent"; the second means "we have not checked".

## Disclosure

- `required` when the source says the use must or should be disclosed and does not mark it optional.
  Where a source defines "should" as a recommendation (DOAJ does), "should" is coded `encouraged`.
- `encouraged` when the source recommends or invites disclosure, or marks it optional.
- `not_required` only for an explicit exemption.
- Language editing: if the exemption covers language editing or polishing in general, `not_required`
  (with any materiality caveat in conditions). If it covers only spelling, grammar or punctuation
  checkers, or "basic tools", disclosure of other language editing is `required`.
- `disclosure_location` lists only places the source names. "Disclose" or "at submission" with no
  place is `unspecified`; the actual wording then goes in conditions.

## Rationale

The ground for the rule, coded only when the source states one: a reason clause ("because",
"as this may", "to protect"), or a principle that heads the rule. `accountability` is used when the
activity's evidence includes a sentence making the author, reviewer or editor responsible for
AI-assisted content. Otherwise `unstated`.

## Activities that need a ruling

- **Due process** (threshold, notification, appeal): coded `permitted_with_conditions` when the source
  states at least one AI-specific element: a consequence for detected or suspected undisclosed AI use,
  contact with the author about AI use, or an appeal route tied to AI concerns. The conditions say
  which elements are stated and which are not. General misconduct or appeal procedures alone are
  `not_addressed`.
- **Licensing published papers for AI training**: coded only when the source addresses whether
  published content may be used to train AI, by the publisher's licensing or by third parties, or
  whether authors consent to that. Text mining, machine access or licensing into reader-facing tools
  without mention of training is not coded. A site copyright footer is not treated as policy. Advice
  to authors about their own material in AI tools (for example, not to let a tool train on an uploaded
  draft) is a different question; it is recorded in the organisation's notes.
- **Publisher's own use**: covers the publisher's and its editors' own AI use on submitted manuscripts.
  Rules for editors are recorded here; conditions say whether the publisher's own systems are described.
- **Funders**: applicant use is coded on the manuscript activities, with conditions saying the subject
  is a grant application. Grant reviewers are coded on reviewer use; the funder's own use on
  publisher's own use. Funders, preprint servers and advisory bodies are shown in the grid but do not
  count in the publisher/journal consensus.

## Contradictions and dating oddities

- `coherence` records a substantive contradiction between two sources of the same organisation that
  give a reader conflicting instructions, with both sides quoted. A tension inside one document, or
  one the publisher could resolve in a sentence, is described in conditions.
- `metadata_inconsistency` records dating, tagging and versioning oddities. They are never counted
  as contradictions.
- `delegates_to_journal: true` is set only where a stored source says journals may set their own
  rules; the notes quote that sentence.

# Corrections and additions

This repository records what organisations say about generative AI, with every cell traced to a quote.
Corrections are welcome, especially from people who work for the organisations recorded here.

## Reporting a wrong or outdated record

Open an issue using the "Correction" template and include:

- the organisation id (the file name in `data/entities/`, for example `wiley`);
- the activity (for example `reviewer_use`) or the field you think is wrong;
- the URL of the page that states the current policy;
- the exact sentence on that page that supports the correction.

A correction is made only from the organisation's own published text. Emails or private statements
cannot be quoted, so they cannot change a record, although they are useful pointers.

## Suggesting an organisation

Open an issue with the organisation's name and the URL of its AI policy page. Pages that need a login
cannot be recorded.

## Editing records yourself

Read `CLAUDE.md` (the project's hard rules) and `schema/coding-conventions.md` first. Quotes must be
copied byte for byte from the stored source text, and `python3 tools/validate.py` must pass.

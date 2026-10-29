# Contributing

- Work on a branch and open a pull request into `main`; CI runs lint, a compile check of all code and the tests.
- `raw` data is never edited. Fixes go in `core` transformations or in a CSV under `reference/`, so every number traces back to what the portal sent.
- Hand-kept lists (agency and payment-name maps, vendor map, focus-area codes, budget stages) live as CSVs in `reference/` so every change has an author and a date.
- A pipeline run that fails any check exports nothing; the last good outputs stay live.
- Keep `docs/checks.md` in step with the checks the code runs.

# Changelog

## 0.2.0, 7 November 2026

- The `update` target: a plain-language instruction to change an app's records, run as a dry run
  through the app's own chat. A string input becomes `{"instruction": …}`; an object can fix its
  own `today`, so a case such as "by Friday" means the same on every run.
- An update's output is flattened for scoring: one change becomes one object with its fields
  beside `op` (and `record_title` for an edit), so the `fields` scorer compares it directly; no
  change is `{"op": "none"}`, several are `{"op": "several", "count": n, …}`.

## 0.1.0, 6 November 2026

- The `forge` runner: runs each Trialmark case through Forge's evaluation API
  (`POST /api/eval/run`) as a dry run on the configured model, for the answer, summarise, draft,
  extract, classify and check targets.
- Before anything is spent, it checks the token, that each model's target is one the token may
  evaluate and supports the step, and that Forge can price the model; the cost estimate uses
  Forge's own prices.
- Every result carries Forge's cost, tokens and time for the step, with the Forge version and the
  fingerprint of the settings the step ran under.
- The token is read from `FORGE_EVAL_TOKEN` or `~/.forge-eval-token`. HTTPS uses certifi's
  certificates, so it works on Pythons that ship without a certificate list.

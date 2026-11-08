# Changelog

## 0.4.0, 8 November 2026

- The `read-reply` target: a person's reply to a follow-up about a commitment, read into what it
  means (done, a new date, waiting on someone, blocked, an update, or unclear, with any dates). A
  case's input is an object holding the reply, the commitment's fields and the day it is read on.
- A reply's output is its reading, so the `fields` scorer compares the outcome and dates with the
  case's reference.

## 0.3.0, 8 November 2026

- An extraction's output is unwrapped for scoring: a vendor's fields, or a contract's
  extraction, so the `fields` scorer compares them with the case's reference directly.
- A classification's output is the account chosen for a single row, so the `label` scorer
  compares it with the case's reference; several rows give a list of accounts.

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

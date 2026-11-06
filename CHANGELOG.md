# Changelog

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

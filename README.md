# trialmark-forge

A [Trialmark](https://github.com/peshwar9/trialmark) runner that acceptance-tests the AI steps of
[Forge](https://www.forgeprivate.com) on the models you choose.

Trialmark decides which model is good enough for a task, with a pass mark fixed before the results
and a record anyone can check. This package lets it test Forge's own work rather than a bare model:
each case runs through Forge's evaluation API, so the answer is the one a Forge user would get,
with the Project's instructions, masking and grounding, or the app's fields, rules and guidance,
applied. Nothing in Forge changes: every call is a dry run.

## What it can test

| Kind | Runs against | A case's input | The output Trialmark scores |
|---|---|---|---|
| `answer`, `summarise`, `draft` | A Project | The question or instruction, as a string | The answer's text, with its citations |
| `extract` | An app that reads documents | The document's text, as a string, or `{"files": [...]}` | The fields or rows, as JSON |
| `classify` | An app with a chart of accounts | `{"rows": [{"description": "...", "direction": "Debit"}]}` | Each row's account, as JSON |
| `check` | An app with checks, such as vendor onboarding | `{"kind": "vendor", "fields": {...}, "detected": [...]}` | Each check's result, as JSON; no model is called |

Options for each kind, such as `{"today": "2026-11-06"}` for extraction, go in the model's
settings (below).

## Install

```
pip install git+https://github.com/peshwar9/trialmark-forge
```

It will be on PyPI as `trialmark-forge` from its first release there.

Trialmark finds the runner once the package is installed; `trialmark plugins` lists it as `forge`.

## The token

The evaluation API takes a bearer token issued by the Forge deployment. The runner reads it from
the `FORGE_EVAL_TOKEN` environment variable when that is set, and otherwise from
`~/.forge-eval-token`. Keep it out of configuration files and repositories.

## A configuration

```json
{
  "test_set": "testset.json",
  "pass_mark": { "metric": "correct", "tolerance_points": 3, "floors": { "grounded": 0.95 }, "choose": "cheapest" },
  "repeats": 3,
  "concurrency": 4,
  "runners": { "forge": { "base_url": "https://www.forgeprivate.com" } },
  "models": [
    { "id": "claude-haiku-4-5-20251001", "runner": "forge",
      "settings": { "target": { "kind": "answer", "project_id": "<the Project's id>" } } },
    { "id": "claude-sonnet-5-5", "runner": "forge",
      "settings": { "target": { "kind": "answer", "project_id": "<the Project's id>" } } }
  ],
  "scorers": [{ "name": "judge", "options": { "model": "claude-opus-5-5", "documents": ["docs/contract.md"] } }],
  "output": "runs/answers.json"
}
```

`trialmark run config.json` prints the plan and an estimate from Forge's own prices, and checks
that the token may evaluate each target and that Forge can price each model, before anything is
spent. Add `--yes` to run it.

**Runner options:** `base_url` (default `https://www.forgeprivate.com`), `token_env` (default
`FORGE_EVAL_TOKEN`), `token_file` (default `~/.forge-eval-token`), `timeout` in seconds (default
300).

**Model settings:** `target` (required: `kind`, and `project_id` or `tracker_id`); `options`,
sent with every case, such as `{"today": "2026-11-06"}` so that an extraction reads relative dates
the same way on every run; `model`, when Forge should run a different model from the entry's id,
or `"default"` for the model Forge would choose; `expected_input_tokens` and
`expected_output_tokens`, to sharpen the estimate.

## What the record holds

Each result carries Forge's cost, tokens and time for the step (measured inside Forge, without the
network), and a note with the Forge version and the fingerprint of the settings the step ran under
(an RFC 8785 hash). Two runs with the same fingerprint tested the same configuration; a changed
fingerprint means someone changed the Project's instructions or the app's setup in between.

A refusal from Forge, such as the daily spend cap, is recorded as that case's error, and the run
carries on. An answer cut off at Forge's output limit is recorded as an error too.

## Licence

Apache-2.0.

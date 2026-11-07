"""The runner against a stand-in for Forge's evaluation API, so the tests run offline."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from trialmark.plugins import find
from trialmark.record import ModelEntry
from trialmark.testset import Case

from trialmark_forge import ForgeError, ForgeRunner

PROJECT = "11111111-1111-4111-8111-111111111111"
APP = "22222222-2222-4222-8222-222222222222"

TARGETS = {
    "forge_version": "5bc99c4abcdef",
    "targets": [
        {"kind": "project", "id": PROJECT, "name": "Model Benchmark",
         "capabilities": [{"kind": k, "settings_fingerprint": "jcs-sha256:p"} for k in ("answer", "summarise", "draft")]},
        {"kind": "app", "id": APP, "name": "Vendor onboarding",
         "capabilities": [{"kind": "extract", "settings_fingerprint": "jcs-sha256:e"}, {"kind": "update", "settings_fingerprint": "jcs-sha256:u"},
                          {"kind": "check", "settings_fingerprint": "jcs-sha256:c"}]},
    ],
    "models": [{"id": "claude-haiku-4-5-20251001", "input_usd_per_mtok": 1, "output_usd_per_mtok": 5}],
}


class Response(io.BytesIO):
    def __init__(self, status: int, body: dict) -> None:
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeForge:
    """Answers like Forge's evaluation API and remembers what it was sent."""

    def __init__(self, token: str = "secret", run_status: int = 200, run_body: dict | None = None, targets_status: int = 200):
        self.token, self.run_status, self.targets_status = token, run_status, targets_status
        self.run_body = run_body
        self.sent: list[dict] = []

    def open(self, req, timeout=None):
        if req.get_header("Authorization") != f"Bearer {self.token}":
            raise urllib.error.HTTPError(req.full_url, 401, "", {}, io.BytesIO(b'{"error":"A valid evaluation token is required."}'))
        if req.full_url.endswith("/api/eval/targets"):
            if self.targets_status != 200:
                raise urllib.error.HTTPError(req.full_url, self.targets_status, "", {}, io.BytesIO(b'{"error":"Not found"}'))
            return Response(200, TARGETS)
        body = json.loads(req.data)
        self.sent.append(body)
        if self.run_status != 200:
            raise urllib.error.HTTPError(req.full_url, self.run_status, "", {}, io.BytesIO(b'{"error":"Today\'s evaluation spend has reached the cap."}'))
        return Response(200, self.run_body or {
            "output": {"text": "Sixty days' written notice (8.1)."},
            "model": body.get("model", "default"),
            "latency_ms": 2140, "input_tokens": 10830, "output_tokens": 120, "cost_usd": 0.0114,
            "finish": "stop", "forge_version": "5bc99c4abcdef", "settings_fingerprint": "jcs-sha256:p",
            "notes": ["masking was applied, so personal details appear as placeholders"],
        })


def runner(fake: FakeForge, monkeypatch, tmp_path) -> ForgeRunner:
    monkeypatch.delenv("FORGE_EVAL_TOKEN", raising=False)
    token_file = tmp_path / "token"
    token_file.write_text(fake.token + "\n")
    return ForgeRunner(base_url="https://forge.test/", token_file=str(token_file), opener=fake)


def answer_model(**extra) -> ModelEntry:
    return ModelEntry(id="claude-haiku-4-5-20251001", runner="forge",
                      settings={"target": {"kind": "answer", "project_id": PROJECT}, **extra})


def test_registered_as_a_trialmark_runner():
    assert find("runner", "forge") is ForgeRunner


def test_an_answer_case_round_trip(monkeypatch, tmp_path):
    fake = FakeForge()
    r = runner(fake, monkeypatch, tmp_path)
    r.prepare()
    out = r.run(answer_model(), Case(id="m1", input="What is the notice period?", reference="60 days"))
    assert fake.sent[0] == {"target": {"kind": "answer", "project_id": PROJECT},
                            "input": {"prompt": "What is the notice period?"}, "model": "claude-haiku-4-5-20251001"}
    assert out.output == "Sixty days' written notice (8.1)."  # the text, so text scorers work unchanged
    assert (out.cost_usd, out.latency_ms, out.input_tokens, out.output_tokens) == (0.0114, 2140, 10830, 120)
    assert out.error is None
    assert "forge 5bc99c4abcde" in out.note and "settings jcs-sha256:p" in out.note and "masking" in out.note


def test_extract_takes_text_and_options_and_returns_json(monkeypatch, tmp_path):
    fake = FakeForge(run_body={"output": {"kind": "vendor", "fields": {"pan": "AABCS1234F"}}, "cost_usd": 0.004,
                               "latency_ms": 900, "finish": None, "settings_fingerprint": "jcs-sha256:e", "notes": []})
    r = runner(fake, monkeypatch, tmp_path)
    m = ModelEntry(id="claude-haiku-4-5-20251001", runner="forge",
                   settings={"target": {"kind": "extract", "tracker_id": APP}, "options": {"today": "2026-11-06"}})
    out = r.run(m, Case(id="v1", input="PAN: AABCS1234F", reference={}))
    assert fake.sent[0]["input"] == {"text": "PAN: AABCS1234F"}
    assert fake.sent[0]["options"] == {"today": "2026-11-06"}
    assert out.output == {"kind": "vendor", "fields": {"pan": "AABCS1234F"}}


def test_a_check_sends_no_model_and_costs_nothing(monkeypatch, tmp_path):
    fake = FakeForge(run_body={"output": {"kind": "vendor", "verdict": {"status": "Active"}}, "cost_usd": 0,
                               "latency_ms": 3, "settings_fingerprint": "jcs-sha256:c", "notes": []})
    r = runner(fake, monkeypatch, tmp_path)
    m = ModelEntry(id="checks", runner="forge", settings={"target": {"kind": "check", "tracker_id": APP}})
    case = Case(id="c1", input={"kind": "vendor", "fields": {}, "detected": []}, reference={})
    assert r.estimate_cost(m, case) == 0.0
    r.run(m, case)
    assert "model" not in fake.sent[0]


def test_default_runs_on_the_model_forge_would_choose(monkeypatch, tmp_path):
    fake = FakeForge()
    r = runner(fake, monkeypatch, tmp_path)
    r.run(answer_model(model="default"), Case(id="m1", input="Q?", reference=""))
    assert "model" not in fake.sent[0]


def test_estimate_uses_forges_prices(monkeypatch, tmp_path):
    r = runner(FakeForge(), monkeypatch, tmp_path)
    cost = r.estimate_cost(answer_model(), Case(id="m1", input="x" * 400, reference=""))
    assert cost == pytest.approx(((11000 + 100) * 1 + 400 * 5) / 1_000_000, rel=0.02)


def test_a_model_forge_cannot_price_stops_before_spending(monkeypatch, tmp_path):
    r = runner(FakeForge(), monkeypatch, tmp_path)
    m = ModelEntry(id="gpt-unknown", runner="forge", settings={"target": {"kind": "answer", "project_id": PROJECT}})
    with pytest.raises(ForgeError, match="cannot price"):
        r.estimate_cost(m, Case(id="m1", input="Q?", reference=""))


def test_a_target_the_token_cannot_reach_is_named(monkeypatch, tmp_path):
    r = runner(FakeForge(), monkeypatch, tmp_path)
    m = ModelEntry(id="x", runner="forge", settings={"target": {"kind": "answer", "project_id": "not-mine"}})
    with pytest.raises(ForgeError, match="not among the targets"):
        r.estimate_cost(m, Case(id="m1", input="Q?", reference=""))


def test_a_kind_the_target_does_not_offer_is_named(monkeypatch, tmp_path):
    r = runner(FakeForge(), monkeypatch, tmp_path)
    m = ModelEntry(id="x", runner="forge", settings={"target": {"kind": "classify", "tracker_id": APP}})
    with pytest.raises(ForgeError, match="does not support classify"):
        r.estimate_cost(m, Case(id="m1", input={}, reference=""))


def test_a_wrong_token_stops_the_run_at_prepare(monkeypatch, tmp_path):
    fake = FakeForge(token="secret")
    r = runner(fake, monkeypatch, tmp_path)
    monkeypatch.setenv("FORGE_EVAL_TOKEN", "wrong")  # the variable wins over the file
    with pytest.raises(ForgeError, match="refused the evaluation token"):
        r.prepare()


def test_the_api_switched_off_is_explained(monkeypatch, tmp_path):
    r = runner(FakeForge(targets_status=404), monkeypatch, tmp_path)
    with pytest.raises(ForgeError, match="not switched on"):
        r.prepare()


def test_no_token_anywhere_is_explained(monkeypatch, tmp_path):
    monkeypatch.delenv("FORGE_EVAL_TOKEN", raising=False)
    r = ForgeRunner(token_file=str(tmp_path / "missing"), opener=FakeForge())
    with pytest.raises(ForgeError, match="No evaluation token"):
        r.prepare()


def test_a_refused_case_is_recorded_as_that_cases_error(monkeypatch, tmp_path):
    r = runner(FakeForge(run_status=429), monkeypatch, tmp_path)
    out = r.run(answer_model(), Case(id="m1", input="Q?", reference=""))
    assert out.output is None and out.error.startswith("Forge 429: Today's evaluation spend")


def test_a_cut_off_answer_is_an_error(monkeypatch, tmp_path):
    fake = FakeForge(run_body={"output": {"text": "Partial"}, "finish": "length", "cost_usd": 0.01, "notes": []})
    out = runner(fake, monkeypatch, tmp_path).run(answer_model(), Case(id="m1", input="Q?", reference=""))
    assert out.error == "The answer was cut off at Forge's output limit."


def test_an_update_is_sent_as_an_instruction_and_flattened_for_scoring(monkeypatch, tmp_path):
    fake = FakeForge(run_body={"output": {"reply": "Moved to Friday.", "changes": [
        {"op": "update", "record_id": "r1", "record_title": "Board pack", "data": {"due": "2026-11-13"}}]},
        "cost_usd": 0.008, "latency_ms": 1200, "finish": "stop", "settings_fingerprint": "jcs-sha256:u", "notes": []})
    r = runner(fake, monkeypatch, tmp_path)
    m = ModelEntry(id="claude-haiku-4-5-20251001", runner="forge", settings={"target": {"kind": "update", "tracker_id": APP}})
    out = r.run(m, Case(id="u1", input="move the board pack to Friday", reference={}))
    assert fake.sent[0]["input"] == {"instruction": "move the board pack to Friday"}
    assert out.output == {"op": "update", "record_id": "r1", "record_title": "Board pack", "due": "2026-11-13", "reply": "Moved to Friday."}


def test_an_update_case_can_fix_its_own_today(monkeypatch, tmp_path):
    fake = FakeForge(run_body={"output": {"reply": "Nothing changed.", "changes": []}, "cost_usd": 0.004, "notes": []})
    r = runner(fake, monkeypatch, tmp_path)
    m = ModelEntry(id="claude-haiku-4-5-20251001", runner="forge", settings={"target": {"kind": "update", "tracker_id": APP}})
    out = r.run(m, Case(id="u2", input={"instruction": "what is due?", "today": "2026-11-13"}, reference={}))
    assert fake.sent[0]["input"] == {"instruction": "what is due?", "today": "2026-11-13"}
    assert out.output == {"op": "none", "reply": "Nothing changed."}


def test_several_changes_are_counted():
    from trialmark_forge import _flatten_changes

    out = _flatten_changes({"reply": "Split.", "changes": [{"op": "add", "data": {}}, {"op": "add", "data": {}}, {"op": "update", "record_id": "x", "data": {}}]})
    assert out["op"] == "several" and out["count"] == 3

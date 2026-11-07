"""A Trialmark runner that tests Forge's own AI steps through Forge's evaluation API.

Each case is sent to ``POST /api/eval/run`` on a Forge deployment, which runs it
through the same code a Forge user reaches (the Project's masking, grounding and
instructions, or the app's fields, rules and guidance) on the model the
configuration names, as a dry run that changes nothing. Forge returns the output
with its cost, tokens and time, the Forge version and a fingerprint of the
settings it ran under, and this runner hands them to Trialmark.

Configuration::

    "runners": { "forge": { "base_url": "https://www.forgeprivate.com" } },
    "models": [
      { "id": "claude-sonnet-5-5", "runner": "forge",
        "settings": { "target": { "kind": "answer", "project_id": "…" } } }
    ]

Runner options:
  base_url:   the Forge deployment (default https://www.forgeprivate.com).
  token_env:  an environment variable holding the evaluation token
              (default FORGE_EVAL_TOKEN); used when it is set.
  token_file: a file holding the token, used otherwise (default ~/.forge-eval-token).
  timeout:    seconds to wait for one case (default 300).

Model settings:
  target:     what to run: ``kind`` (answer, summarise, draft, extract, classify,
              update, check) and ``project_id`` or ``tracker_id``. Required.
  options:    passed to Forge with every case, such as ``{"today": "2026-11-06"}``
              for extraction, so a relative date means the same on every run.
  model:      the model Forge should run, when it differs from the entry's id.
              ``"default"`` runs the step on the model Forge would choose.
  expected_input_tokens, expected_output_tokens: for the cost estimate only.

A case's input is a string or an object. A string becomes ``{"prompt": …}`` for
answer, summarise and draft, ``{"instruction": …}`` for update, and ``{"text": …}``
for extract; an object is sent as it is, so an update case can fix its own
``today``. For answer, summarise and draft the output Trialmark scores is the
answer's text, so text scorers such as ``judge`` and ``checklist`` work unchanged;
for update it is the change flattened into fields (see ``_flatten_changes``); for
the other kinds it is Forge's JSON output.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from trialmark import RunOutput

__version__ = "0.2.0"

DEFAULT_BASE_URL = "https://www.forgeprivate.com"
TEXT_KINDS = ("answer", "summarise", "draft")
KINDS = (*TEXT_KINDS, "extract", "classify", "update", "check")

# Rough sizes for the estimate, from Forge's own runs: an answer reads about ten
# thousand tokens of retrieved passages; the other steps read mostly their input.
_EXPECTED_INPUT = {"answer": 11000, "summarise": 20000, "draft": 20000, "extract": 2000, "classify": 1500, "update": 7000, "check": 0}
_EXPECTED_OUTPUT = {"answer": 400, "summarise": 800, "draft": 1200, "extract": 600, "classify": 300, "update": 250, "check": 0}


def _tls_context() -> ssl.SSLContext:
    """Certificates from certifi, so HTTPS works on Pythons that ship without a
    certificate list (python.org's macOS builds), and the system's otherwise."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _flatten_changes(out: dict[str, Any]) -> dict[str, Any]:
    """An update's output as fields a scorer can compare.

    One change becomes one flat object, its fields beside "op" (and "record_title"
    for an edit), so the ``fields`` scorer checks a reference such as
    ``{"op": "update", "record_title": "Board pack", "due": "2026-11-13"}``. No
    change is ``{"op": "none"}``; several are ``{"op": "several", "count": n,
    "changes": [...]}``. The chat's reply is kept under "reply".
    """
    changes = out.get("changes") or []
    reply = out.get("reply", "")
    if not changes:
        return {"op": "none", "reply": reply}
    if len(changes) > 1:
        return {"op": "several", "count": len(changes), "changes": changes, "reply": reply}
    c = changes[0]
    flat = {k: v for k, v in c.items() if k != "data"}
    flat.update(c.get("data") or {})
    flat["reply"] = reply
    return flat


class ForgeError(Exception):
    """A refusal from Forge that should stop a run before it spends anything."""


class ForgeRunner:
    """Runs each case through one of Forge's capabilities on the configured model."""

    costs_money = True

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token_env: str = "FORGE_EVAL_TOKEN",
        token_file: str | None = None,
        timeout: float = 300,
        base_dir: Path | None = None,
        opener: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_env = token_env
        self.token_file = Path(token_file).expanduser() if token_file else Path.home() / ".forge-eval-token"
        self.timeout = float(timeout)
        # For tests: anything with urllib's open(request, timeout=) interface.
        self._opener = opener or urllib.request.build_opener(urllib.request.HTTPSHandler(context=_tls_context()))
        self._targets: dict[str, Any] | None = None
        self._lock = threading.Lock()

    # --- talking to Forge -------------------------------------------------------

    def _token(self) -> str:
        token = os.environ.get(self.token_env, "").strip()
        if token:
            return token
        if self.token_file.is_file():
            token = self.token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
        raise ForgeError(
            f"No evaluation token: set {self.token_env}, or save the token in {self.token_file}."
        )

    def _call(self, method: str, path: str, body: Any = None) -> tuple[int, dict[str, Any]]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
                "User-Agent": f"trialmark-forge/{__version__}",
            },
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as res:
                return res.status, json.loads(res.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8") or "{}")
            except ValueError:
                payload = {}
            return e.code, payload

    def targets(self) -> dict[str, Any]:
        """Forge's list of what this token may evaluate, fetched once per run."""
        with self._lock:
            if self._targets is None:
                status, body = self._call("GET", "/api/eval/targets")
                if status == 401:
                    raise ForgeError("Forge refused the evaluation token. Check it, and save it again if it has changed.")
                if status == 404:
                    raise ForgeError(f"The evaluation API is not switched on at {self.base_url}.")
                if status != 200:
                    raise ForgeError(f"Forge answered {status} when listing targets: {body.get('error', body)}")
                self._targets = body
            return self._targets

    # --- the runner interface ---------------------------------------------------

    def prepare(self) -> None:
        # Reaches Forge and checks the token once, before any case is run.
        self.targets()

    def _target(self, model: Any) -> dict[str, Any]:
        t = model.settings.get("target")
        if not isinstance(t, dict) or t.get("kind") not in KINDS:
            raise ForgeError(
                f"Model '{model.id}' needs settings.target with a kind from {', '.join(KINDS)} "
                "and a project_id or tracker_id."
            )
        target_id = t.get("project_id") if t["kind"] in TEXT_KINDS else t.get("tracker_id")
        if not target_id:
            raise ForgeError(f"Model '{model.id}': a {t['kind']} target needs {'project_id' if t['kind'] in TEXT_KINDS else 'tracker_id'}.")
        listed = next((x for x in self.targets().get("targets", []) if x.get("id") == target_id), None)
        if listed is None:
            raise ForgeError(f"Model '{model.id}': {target_id} is not among the targets this token may evaluate.")
        if t["kind"] not in [c.get("kind") for c in listed.get("capabilities", [])]:
            offered = ", ".join(c.get("kind", "?") for c in listed.get("capabilities", []))
            raise ForgeError(f"Model '{model.id}': {listed.get('name')} does not support {t['kind']} (it offers {offered}).")
        return t

    def _forge_model(self, model: Any) -> str | None:
        chosen = model.settings.get("model", model.id)
        return None if chosen == "default" else chosen

    def _input(self, kind: str, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            if kind in TEXT_KINDS:
                return {"prompt": value}
            return {"instruction": value} if kind == "update" else {"text": value}
        raise ForgeError(f"A {kind} case's input must be a string or an object.")

    def estimate_cost(self, model: Any, case: Any) -> float | None:
        kind = self._target(model)["kind"]
        if kind == "check":
            return 0.0
        chosen = self._forge_model(model)
        price = next((m for m in self.targets().get("models", []) if m.get("id") == chosen), None)
        if price is None:
            if chosen is None:
                return None  # the model Forge would choose; its price is not listed per target
            raise ForgeError(f"Model '{model.id}': Forge cannot price {chosen}, so it will not run it.")
        s = model.settings
        size = len(json.dumps(case.input)) // 4
        tokens_in = float(s.get("expected_input_tokens", _EXPECTED_INPUT[kind])) + size
        tokens_out = float(s.get("expected_output_tokens", _EXPECTED_OUTPUT[kind]))
        return (tokens_in * price["input_usd_per_mtok"] + tokens_out * price["output_usd_per_mtok"]) / 1_000_000

    def run(self, model: Any, case: Any) -> RunOutput:
        target = self._target(model)
        kind = target["kind"]
        body: dict[str, Any] = {"target": target, "input": self._input(kind, case.input)}
        if model.settings.get("options"):
            body["options"] = model.settings["options"]
        chosen = self._forge_model(model)
        if chosen and kind != "check":
            body["model"] = chosen
        status, r = self._call("POST", "/api/eval/run", body)
        if status != 200:
            return RunOutput(output=None, error=f"Forge {status}: {r.get('error', 'no message')}"[:500])

        out = r.get("output")
        if kind in TEXT_KINDS and isinstance(out, dict):
            out = out.get("text", "")
        elif kind == "update" and isinstance(out, dict):
            out = _flatten_changes(out)
        error = None
        if r.get("finish") == "length":
            error = "The answer was cut off at Forge's output limit."
        # The version and the fingerprint go on every result, so the record shows
        # which Forge and which configuration each answer came from.
        note = " ".join(
            [f"forge {str(r.get('forge_version', '?'))[:12]}", f"settings {r.get('settings_fingerprint', '?')}"]
            + [str(n) for n in r.get("notes", []) if n]
        )
        return RunOutput(
            output=out,
            cost_usd=float(r.get("cost_usd") or 0.0),
            # Forge's own time for the step, without the network between here and Forge.
            latency_ms=int(r["latency_ms"]) if isinstance(r.get("latency_ms"), (int, float)) else None,
            input_tokens=int(r.get("input_tokens") or 0),
            output_tokens=int(r.get("output_tokens") or 0),
            error=error,
            note=note,
        )


__all__ = ["ForgeRunner", "ForgeError", "__version__"]

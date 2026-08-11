"""Decompose a run's trace into the data behind the Trajectory drawer.

A pure function over already-parsed trace events — no web dependencies, no filesystem — so it is
unit-testable without a server, a model or a run. Ported from a sibling project's own iteration
builder, which shipped this shape first; the DECOMPOSITION is theirs, the tool vocabulary is ours
(`read_skill` and the six `validate_*` tools, against their fetch/search/generate/validate set).

An RLM run is a sequence of `main_step` REPL turns — the planner's reasoning, the Python it ran, and
that code's output. `tool_call`/`sub_call` events that follow a turn belong to it: its code invoked
them. So there are TWO views of one run, on two different clocks, and conflating them is the mistake
this module exists to avoid:

- `iterations` — the turns, in turn order. Content is always reliable. Per-turn TIMING is attached
  only when the trace carries live `main_step` timestamps (rlm-harness backfills them as each turn
  is parsed). An older trace flushed every `main_step` at finalize, so their timestamps cluster at
  one instant; that is detected and per-turn durations are omitted rather than invented.
- `timeline` — the tool and sub-LM calls, which are ALWAYS recorded live with real timestamps. This
  is the honest "where did the time go" signal either way.

Why a server-side decomposition rather than handing the raw trace to the browser: a trace can hold
full ingested source text (CLAUDE.md invariant 29 already calls the trace endpoints a materially
different exposure than the rest of this no-auth API), and the per-field caps here are what keep a
multi-megabyte REPL output from being shipped to a page that only ever renders a preview of it.
"""

from __future__ import annotations

from typing import Any

#: Per-field character cap. Generous — rarely hit — and bounds a pathological REPL output, which in
#: this project can be a whole corpus span the model printed while reading (invariant 52 records the
#: same reasoning for why the live ticker streams an output's SIZE and never its text).
_CAP = 16_000

#: Bulky text blobs an unrecognised tool might carry, dropped from the generic fallback entry so one
#: unknown tool cannot swamp the detail view.
_BULKY_FIELDS = frozenset({"raw", "preview", "spec", "output", "reasoning", "result", "processed"})
_SCALAR_MAX = 200

#: Below this, a spread of `main_step` timestamps is finalize-flush clustering rather than real
#: per-turn timing. A genuine LM turn costs seconds, so two live turns always span more than this.
_LIVE_TIMING_SPAN_S = 1.0


def _preview(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= _CAP else text[:_CAP] + "\n…[truncated — full text in the trace]"


def _step_key(event: dict) -> int:
    raw = str(event.get("step_id", ""))
    return int(raw) if raw.lstrip("-").isdigit() else 1 << 30


def _gap(ts: float | None, prev: float | None) -> float | None:
    return round(ts - prev, 3) if (ts is not None and prev is not None) else None


def _is_pathlike(value: str) -> bool:
    return "/" in value or value.startswith(("~", "\\"))


def _scalar_fields(payload: dict) -> dict:
    """The short scalar fields of an UNRECOGNISED tool call, so the detail view still shows
    something. Drops the entry's own keys, bulky blobs, non-scalars, over-cap and path-like
    strings."""
    out: dict = {}
    for key, value in payload.items():
        if key in ("tool", "ok") or key in _BULKY_FIELDS:
            continue
        if not isinstance(value, (str, int, float)):
            continue
        if isinstance(value, str) and (len(value) > _SCALAR_MAX or _is_pathlike(value)):
            continue
        out[key] = value
    return out


def _tool_entry(payload: dict, gap: float | None) -> dict:
    """One `tool_call` → a UI-ready entry: what was called, what it was given, what it returned."""
    tool = payload.get("tool") or ""
    args = payload.get("args") or {}
    entry: dict = {"kind": "tool", "tool": tool, "ok": payload.get("ok"), "duration_s": gap}
    if tool == "read_skill":
        entry.update(
            label="skill",
            target=args.get("name"),
            result_len=payload.get("result_len"),
            content=_preview(payload.get("preview")),
        )
    elif tool == "list_skills":
        entry.update(label="skill", target="(catalog)", content=_preview(payload.get("result")))
    elif tool.startswith("validate_"):
        # The pre-SUBMIT validator. `result` is the verdict sentence — the single most useful thing
        # in a failed run's trace, because it says exactly what the model was told to fix and how
        # many times it went round (a marker in prose, an invented coordinate, a shape error).
        verdict = payload.get("result")
        entry.update(
            label="validate",
            target=tool.removeprefix("validate_"),
            verdict=_preview(verdict),
            passed=bool(verdict) and not str(verdict).startswith("Validation failed"),
        )
    else:
        entry["label"] = tool or "tool"
        fields = _scalar_fields(payload)
        if fields:
            entry["fields"] = fields
    return entry


def _sub_entry(payload: dict, gap: float | None) -> dict:
    """One `sub_call` — a sub-LM escalation — as its question and the answer it came back with."""
    return {
        "kind": "lifeline",
        "label": "lifeline",
        "model": payload.get("name") or payload.get("model"),
        "duration_s": gap,
        "input": _preview(payload.get("input")),
        "output": _preview(payload.get("processed") or payload.get("raw")),
        "error": payload.get("error"),
    }


def build_trajectory(events: list[dict]) -> dict:
    """`{started_at, total_s, ok, error, timing_note, per_turn_timing, initial, iterations,
    timeline}` for one run's trace events.

    Never raises on a partial or malformed trace: a run that was cancelled or timed out mid-flight
    has no `run_end`, and that is exactly the run someone most wants to look at.
    """
    ordered = sorted(events, key=_step_key)

    meta: dict = {}
    ts0: float | None = None
    for event in ordered:
        if event.get("type") == "run_start":
            meta = (event.get("payload") or {}).get("meta") or {}
            ts0 = event.get("ts")
            break

    ts_end: float | None = None
    ok: bool | None = None
    error: str | None = None
    for event in reversed(ordered):
        if event.get("type") in ("run_end", "result", "final"):
            ts_end = event.get("ts")
            if event.get("type") == "run_end":
                payload = event.get("payload") or {}
                ok = payload.get("ok")
                error = payload.get("error")
            break

    iterations: list[dict] = []
    for event in ordered:
        if event.get("type") != "main_step":
            continue
        payload = event.get("payload") or {}
        iterations.append(
            {
                "turn": payload.get("turn"),
                "reasoning": _preview(payload.get("reasoning")),
                "code": _preview(payload.get("code")),
                "output": _preview(payload.get("output")),
                "_ts": event.get("ts"),
            }
        )
    iterations.sort(key=lambda it: it["turn"] if it["turn"] is not None else 1 << 30)

    step_ts = [it["_ts"] for it in iterations if isinstance(it["_ts"], (int, float))]
    per_turn = len(step_ts) >= 2 and (max(step_ts) - min(step_ts)) > _LIVE_TIMING_SPAN_S
    for i, iteration in enumerate(iterations):
        iteration["index"] = i
        if per_turn and isinstance(iteration["_ts"], (int, float)):
            iteration["rel_s"] = round(iteration["_ts"] - ts0, 3) if ts0 is not None else None
            nxt = iterations[i + 1]["_ts"] if i + 1 < len(iterations) else ts_end
            iteration["duration_s"] = (
                round(nxt - iteration["_ts"], 3) if isinstance(nxt, (int, float)) else None
            )
        iteration.pop("_ts", None)

    timeline: list[dict] = []
    prev = ts0
    for event in ordered:
        kind = event.get("type")
        ts = event.get("ts")
        if kind not in ("tool_call", "sub_call") or ts is None:
            continue
        payload = event.get("payload") or {}
        entry = (
            _tool_entry(payload, _gap(ts, prev))
            if kind == "tool_call"
            else _sub_entry(payload, _gap(ts, prev))
        )
        entry["seq"] = len(timeline)
        entry["rel_s"] = round(ts - ts0, 3) if ts0 is not None else None
        timeline.append(entry)
        prev = ts

    # Attribute each call to the turn whose code produced it — ONLY with live per-turn timing, since
    # otherwise every `main_step` timestamp is the finalize instant and the mapping is meaningless.
    # A turn's code runs after its own parse and before the next turn's, so a call belongs to the
    # turn with the greatest `rel_s` not exceeding the call's.
    if per_turn:
        marks = sorted(
            (it["rel_s"], it["index"])
            for it in iterations
            if isinstance(it.get("rel_s"), (int, float))
        )
        for entry in timeline:
            rel = entry.get("rel_s")
            if rel is None or not marks:
                continue
            assigned = marks[0][1]
            for mark_rel, mark_idx in marks:
                if mark_rel <= rel:
                    assigned = mark_idx
                else:
                    break
            entry["turn_index"] = assigned

    note = (
        "Per-turn timing is live — captured as each turn was parsed."
        if per_turn
        else "Per-turn timing isn't available for this trace (the turns weren't live-stamped, or "
        "the run was too short to span); the tool timeline still carries real times."
    )
    return {
        "started_at": ts0,
        "total_s": round(ts_end - ts0, 3) if (ts_end is not None and ts0 is not None) else None,
        "ok": ok,
        "error": error,
        "timing_note": note,
        "per_turn_timing": per_turn,
        "initial": {
            # `run_start`'s meta is whatever `worker.py` stamped. `task` is the one key this project
            # reliably writes; the rest is passed through so a richer meta needs no change here.
            "task": meta.get("task"),
            "meta": {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))},
        },
        "iterations": iterations,
        "timeline": timeline,
    }

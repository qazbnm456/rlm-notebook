#!/usr/bin/env python3
"""Build the static, no-server PLAYGROUND from this repo's real web UI and real notebooks.

The whole point: `app.js`, `style.css` and `i18n.js` are COPIED VERBATIM and never edited. The
playground is the product, running against a network shim instead of a server — so a screenshot of
it is a screenshot of the real thing, and it cannot drift into a mock-up of a UI we no longer ship.
Everything playground-specific lives in `src/` and is layered ON TOP: `shim.js` replaces three
browser APIs, `chrome.css` styles the extra furniture with the app's OWN design tokens, and
`tour.js` is data.

Usage:  uv run python playground/build.py [--out DIR] [--audio-seconds N]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "rlm_notebook" / "web"
SRC = Path(__file__).resolve().parent / "src"
VENDOR = Path(__file__).resolve().parent / "vendor"
NOTEBOOKS = ROOT / "notebooks"
TRACES = ROOT / "traces"

#: Verbatim copies. Editing any of these in `dist/` is the one thing that breaks the guarantee
#: above, which is why the build always overwrites them from the package.
VERBATIM = ("app.js", "style.css", "i18n.js")

#: Per-source ingested-text cap. The source viewer stays useful and citations still resolve, but a
#: playground published on the open web does not rehost whole third-party articles — every demo
#: source is somebody else's blog post. `_truncate` marks where it cut so nothing looks complete
#: when it is not.
MAX_SOURCE_CHARS = 6000

#: Which notebooks ship, in picker order, with the one-line pitch the scenario modal shows. Keep
#: this list explicit rather than globbing `notebooks/`: a local notebook is the author's own
#: working data and must never be published by accident.
SCENARIOS = [
    # ORDER IS THE DEFAULT: the first entry is what a first-time visitor lands on.
    #
    # The three English notebooks and the three Traditional Chinese ones are built from the SAME
    # source sets. That pairing is the point: `RN_OUTPUT_LANGUAGE` is the only difference between
    # each pair, so a reader can switch between them and see invariant 39 directly — model-authored
    # prose follows the READER while `source_id`, `locator` and every `quote` stay in the source's
    # own words and language.
    #
    # English leads because this is a public product page whose README, repo and install commands
    # are English; the Chinese set is one click away in the scenario picker.
    {
        "id": "nb-en-security",
        "lang": "English",
        "label": "AI security & exploits",
        "blurb": "Three write-ups on AI-reconstructed exploits and agentic-AI defence. The most "
        "compact corpus, so a run is quick to follow end to end.",
        "badge": "START HERE",
    },
    {
        "id": "nb-en-harness",
        "lang": "English",
        "label": "LLM vulnerability harnesses",
        "blurb": "Four engineering posts on building AI harnesses for vulnerability discovery — "
        "why the scaffolding around a model matters more than the model.",
        "badge": "ENGLISH",
    },
    {
        "id": "nb-en-evolution",
        "lang": "English",
        "label": "Self-improving AI",
        "blurb": "A paper and three lab write-ups on evolutionary and self-improving systems.",
        "badge": "ENGLISH",
    },
    {
        "id": "nb-443d7daa",
        "lang": "Traditional Chinese",
        "label": "AI 資安挑戰與漏洞分析",
        "blurb": "The same three security sources, answered in Traditional Chinese. Compare it with "
        "the English notebook above: same corpus, same citations, different reader.",
        "badge": "中文",
    },
    {
        "id": "nb-d22c2a9a",
        "lang": "Traditional Chinese",
        "label": "Trinity 與演化式 AI",
        "blurb": "Evolutionary AI in Traditional Chinese, including Japanese source material — the "
        "script and register rules are visible here.",
        "badge": "中文",
    },
    {
        "id": "nb-6f2d49d3",
        "lang": "Traditional Chinese",
        "label": "LLM 漏洞掃獵框架",
        "blurb": "The richest corpus: five sources, a chat thread, a note and a 39-turn podcast. "
        "Predates `instructions.NATURAL_REGISTER`, so it still carries the calque that rule now "
        "prevents — kept as honest history, which is why it does not greet anybody.",
        "badge": "中文",
    },
]



def _truncate(text: str) -> str:
    if len(text) <= MAX_SOURCE_CHARS:
        return text
    return text[:MAX_SOURCE_CHARS].rstrip() + (
        "\n\n[… truncated for the public playground. The full text is only ever in your own local "
        "notebook — install rlm-notebook and ingest the source yourself to read all of it.]"
    )


def load_notebook(nb_id: str) -> tuple[dict, dict]:
    """Return `(api_response, source_texts)` computed by the REAL response models.

    This is the load-bearing choice in the whole build. Rendering a notebook the way the server
    does means verifying every citation's coordinate, locating every `answer_span`, and computing
    two staleness verdicts — `citations.py` and `api.py` already do all of it, correctly, and a
    JavaScript re-implementation in the shim would be a second answer that drifts from the first.
    So the build imports `api._notebook_response` and ships what it produced: the fixture IS the
    response, checkmarks and all, and a playground citation is verified by the same code that
    verifies a real one.

    Needs the `api` extra (`uv run --extra api python playground/build.py`)."""
    from rlm_notebook.api import _notebook_response
    from rlm_notebook.schema import Notebook

    raw = json.loads((NOTEBOOKS / f"{nb_id}.json").read_text(encoding="utf-8"))
    notebook = Notebook.model_validate(raw)
    response = _notebook_response(notebook).model_dump(mode="json")
    # `GET /sources/{id}` is the one response that carries a source's FULL text (invariant 31), so
    # it is the one the cap applies to.
    texts = {
        s.id: {
            "id": s.id,
            "kind": s.kind,
            "origin": s.origin,
            "flags": s.flags,
            "preview": s.preview,
            "blocks": [
                {"locator": b.locator, "text": _truncate(b.text)} for b in s.blocks
            ],
        }
        for s in notebook.sources
    }
    return response, texts


def precompute_runs(nb_id: str) -> dict[str, dict]:
    """Per run id: the ticker events and the Trajectory decomposition, both computed by the REAL
    code (`api._translate_trace_event`, `trajectory.build_trajectory`).

    Same reasoning as `load_notebook`: the shim replays what those functions produced rather than
    re-deriving it in JavaScript. It also means the playground's reasoning ticker shows the model's
    ACTUAL words from a run that really happened, which is the one thing a hand-written mock could
    never be."""
    from rlm_notebook.api import _translate_trace_event
    from rlm_notebook.trajectory import build_trajectory

    runs: dict[str, dict] = {}
    for run_id, events in _read_traces(nb_id).items():
        meta = next(
            (e["payload"].get("meta", {}) for e in events if e.get("type") == "run_start"), {}
        )
        runs[run_id] = {
            "task": meta.get("task", ""),
            "ticker": [_translate_trace_event(e) for e in events],
            "trajectory": build_trajectory(events),
        }
    return runs


def _read_traces(nb_id: str) -> dict[str, list]:
    """Real trace events, keyed by run id, for the SSE shim to replay.

    Replaying a REAL trace is why the ticker in the playground shows the model's own reasoning
    rather than invented filler — the same reason the fixtures are real notebooks. A run whose trace
    was pruned (`RN_TRACE_RETENTION_DAYS`) simply has no entry, and the shim synthesises a short
    generic one instead of failing.
    """
    out: dict[str, list] = {}
    if not TRACES.is_dir():
        return out
    for path in sorted(TRACES.glob(f"{nb_id}-*.jsonl")):
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                break  # a torn final line: the writer was mid-flush, same rule as `run_trajectory`
        if events:
            out[path.stem] = events
    return out


def build_index() -> str:
    """The app's own `index.html`, with absolute asset paths made relative and the playground
    layered in. Rewriting rather than forking: a new element in the product's markup shows up here
    on the next build instead of silently missing."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    # `/style.css` etc. are absolute because the server mounts assets at the root; a GitHub Pages
    # subdirectory (`/rlm-notebook/`) is not the root, so every one of them would 404.
    html = re.sub(r'(href|src)="/([^"]+)"', r'\1="./\2"', html)
    assert '="/' not in html, "an absolute asset path survived the rewrite"
    html = html.replace(
        '<link rel="stylesheet" href="./style.css" />',
        '<link rel="stylesheet" href="./style.css" />\n'
        '<link rel="stylesheet" href="./driver.css" />\n'
        '<link rel="stylesheet" href="./chrome.css" />',
    )
    # The shim MUST be evaluated before `app.js`, which captures nothing but calls the globals it
    # replaces — so ordering is the entire contract between the two files.
    html = html.replace(
        '<script src="./i18n.js"></script>',
        '<script src="./tour.js"></script>\n<script src="./shim.js"></script>\n'
        '<script src="./i18n.js"></script>',
    )
    # `chrome.js` runs AFTER the app so the header it augments already exists.
    html = html.replace(
        '<script src="./app.js"></script>',
        '<script src="./app.js"></script>\n'
        '<script src="./driver.js.iife.js"></script>\n'
        '<script src="./chrome.js"></script>\n'
        '<script src="./director.js"></script>',
    )
    html = html.replace(
        "<title>rlm-notebook</title>", "<title>rlm-notebook — interactive playground</title>"
    )
    return html


def _duration_s(path: Path) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def trim_audio(nb_id: str, dest: Path, seconds: int) -> dict | None:
    """Copy or trim the episode, and REPORT whether it was cut.

    `preload="none"` (invariant 42) means the browser fetches audio only when someone presses play,
    so page weight is not the constraint it looks like — the cap is generous, and a `short` episode
    usually arrives whole. What the cap does create is a transcript longer than its audio: a `long`
    episode's later lines would seek past the end and silently do nothing. The transcript is NOT
    truncated to match (that would understate the tier the episode is demonstrating), so the flag
    returned here is what lets the page say the audio stops early instead of looking broken."""
    src = NOTEBOOKS / "audio" / f"{nb_id}.mp3"
    if not src.exists():
        return None
    full = _duration_s(src)
    # NO CAP is the default, and an uncapped episode is COPIED BYTE-FOR-BYTE. edge-tts already ships
    # 48 kbps / 24 kHz mono, which is where speech should be — re-encoding at "64k for the web" was
    # UPSCALING: it made the files bigger (9.8MB of capped audio against 17.6MB of complete originals
    # where the estimate said 7.9MB) and added a generation of loss for nothing. Measured, after
    # guessing wrong twice.
    #
    # Page weight is not the constraint it looks like: `preload="none"` (invariant 42) means a
    # browser fetches an episode only when somebody presses play.
    if seconds <= 0 or not shutil.which("ffmpeg") or not full or full <= seconds:
        shutil.copy2(src, dest)
        return {"seconds": round(full, 1), "trimmed": False}
    # A cap re-encodes at the SOURCE's own bitrate, so trimming never doubles as a quality change.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-t", str(seconds),
         "-b:a", "48k", "-ac", "1", "-ar", "24000", str(dest)],
        check=True,
    )
    return {"seconds": float(seconds), "trimmed": True, "full_seconds": round(full, 1)}
    return {"seconds": round(full, 1), "trimmed": False}


#: Text that could only have come from this repository's own documentation. The model READS this
#: project's skill files mid-run (invariant 65 wires them in with `discovery="inject"`), so its
#: reasoning quotes them back: internal notes, invariant numbers and measurement history, on a page
#: meant to show a reader what the product does.
#:
#: DELIBERATELY NARROW. A first pass also listed `rlm_notebook` and `rlm_harness`, which redacted 339
#: strings — every `task` field among them — and would have gutted the drawer it was protecting.
#: Those are package names that ship in the wheel; they are not private. What is private is the
#: PROSE of the internal docs.
_INTERNAL_MARKERS = (
    "TraceRecorder",
    "corpus-navigation",
    "podcast-craft",
    "AGENTS.md",
    "CHANGELOG.md",
    "read_skill",
)

#: Only long strings are candidates. A short field can contain a marker incidentally; a paragraph
#: containing one is the model quoting a document back.
_REDACT_MIN_CHARS = 180

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")


def redact_traces(fixtures: dict) -> int:
    """Strip anything from the recorded runs that is about THIS MACHINE rather than the demo.

    A trace is the one artifact here that can carry text nobody chose to publish: the planner's own
    reasoning, the code it wrote, and whatever it read. The audit that prompted this found no local
    paths, no username, no hostnames and no credentials — but it did find a run quoting this repo's
    internal skill files at length, because the model had read them.

    Redaction happens at the STRING level across the runs, so it reaches reasoning, code cells and
    tool verdicts alike without needing to know which field a given event uses.
    """
    redacted = 0

    def clean(value):
        nonlocal redacted
        if isinstance(value, str):
            if len(value) >= _REDACT_MIN_CHARS and any(m in value for m in _INTERNAL_MARKERS):
                redacted += 1
                return "[internal project notes the model read during this run, omitted here]"
            new = _EMAIL.sub("[email omitted]", value)
            if new != value:
                redacted += 1
            return new
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    # Internal-doc prose can only appear in a RUN — a source is somebody else's article.
    fixtures["runs"] = clean(fixtures["runs"])

    # Contact details, though, arrive in the ingested SOURCES: a press release prints its press
    # officer's address, and republishing it on another domain hands a scraper a fresh copy. The
    # sources are the reader-facing text, so this covers the whole fixture rather than the runs.
    def scrub_emails(value):
        nonlocal redacted
        if isinstance(value, str):
            new_value = _EMAIL.sub("[email omitted]", value)
            if new_value != value:
                redacted += 1
            return new_value
        if isinstance(value, dict):
            return {k: scrub_emails(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub_emails(v) for v in value]
        return value

    for key in ("notebooks", "sources", "scenarios"):
        fixtures[key] = scrub_emails(fixtures[key])

    print(f"  redacted {redacted} string(s) carrying internal notes or contact detail")
    return redacted


def anonymise_models(fixtures: dict) -> None:
    """Replace every model identifier with a neutral label, everywhere in the fixture.

    Which models this project runs against is nobody's business on a public product page, and the
    names reach further than the one field that holds them: `run_start.meta` carries `main_model`
    and `sub_model`, and the planner's own reasoning quotes them too. So the names are COLLECTED
    from the meta fields (never hardcoded, so a future model is covered without anyone remembering
    this function) and then substituted across the serialised fixture — prose included.

    Labels are stable and ordered, so the same model reads as the same model across every run and a
    reader can still see that two different ones were involved.
    """
    names: list[str] = []
    for run in fixtures["runs"].values():
        meta = ((run.get("trajectory") or {}).get("initial") or {}).get("meta") or {}
        for key in ("main_model", "sub_model"):
            value = meta.get(key)
            if isinstance(value, str) and value and value not in names:
                names.append(value)
    if not names:
        return

    # Longest first: a bare name can be a substring of a prefixed one (`gpt-5.6-luna` inside
    # `openai/gpt-5.6-luna`), and replacing the short one first would leave `openai/model-b`.
    mapping = {n: f"model-{chr(ord('a') + i)}" for i, n in enumerate(names)}
    blob = json.dumps(fixtures, ensure_ascii=False)
    for name in sorted(mapping, key=len, reverse=True):
        blob = blob.replace(name, mapping[name])
    fixtures.clear()
    fixtures.update(json.loads(blob))
    print(f"  anonymised {len(mapping)} model name(s): {', '.join(mapping.values())}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "dist"))
    ap.add_argument("--deploy", metavar="DIR",
                    help="also mirror the build into DIR (e.g. a GitHub Pages checkout). Replaces "
                         "DIR's contents; DIR is created if absent.")
    # 0 by default: the episodes are the product's real output and a capped one cannot demonstrate
    # the transcript following the playhead to the end. `preload="none"` (invariant 42) means none of
    # it is fetched until somebody presses play.
    ap.add_argument("--audio-seconds", type=int, default=0,
                    help="cap per episode in seconds; 0 keeps every episode whole. A shorter "
                         "episode is never padded or cut, so `short` tiers usually arrive intact.")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "audio").mkdir(parents=True)

    for name in VERBATIM:
        shutil.copy2(WEB / name, out / name)
    for name in ("shim.js", "chrome.css", "tour.js", "chrome.js", "director.js"):
        shutil.copy2(SRC / name, out / name)
    # Vendored, not CDN-loaded: the published page keeps no third-party origin in its critical path.
    for name in ("driver.js.iife.js", "driver.css"):
        shutil.copy2(VENDOR / name, out / name)
    (out / "index.html").write_text(build_index(), encoding="utf-8")

    fixtures = {"scenarios": [], "notebooks": {}, "sources": {}, "runs": {}}
    for scenario in SCENARIOS:
        nb_id = scenario["id"]
        response, texts = load_notebook(nb_id)
        fixtures["notebooks"][nb_id] = response
        fixtures["sources"][nb_id] = texts
        fixtures["runs"].update(precompute_runs(nb_id))
        audio = trim_audio(nb_id, out / "audio" / f"{nb_id}.mp3", args.audio_seconds)
        pod = response.get("podcast") or {}
        # A ⌁ pill is rendered from a persisted `run_id`, and the drawer 404s if the trace behind it
        # was pruned (`RN_TRACE_RETENTION_DAYS`) or the run predates the API path. In the product
        # that degrades one affordance and nothing else (invariant 29); on a product PAGE it is a
        # reader pressing the headline feature and getting an error. So an artifact whose trace is
        # gone simply does not advertise one here. Honest by subtraction: the demo never offers an
        # affordance it cannot fulfil, and never shows somebody else's trace in its place.
        have = set(fixtures["runs"])
        dropped = 0
        for art in [response.get("overview"), response.get("podcast"), *response.get("turns", [])]:
            if art and art.get("run_id") and art["run_id"] not in have:
                art["run_id"] = None
                dropped += 1
        if dropped:
            print(f"  {nb_id}: {dropped} artifact(s) had no surviving trace; ⌁ pill withheld")

        fixtures["scenarios"].append({
            **scenario,
            "title": response.get("title"),
            "audio": audio,
            "utterances": len(pod.get("utterances") or []),
        })

    anonymise_models(fixtures)
    redact_traces(fixtures)

    (out / "fixtures.json").write_text(
        json.dumps(fixtures, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    if args.deploy:
        # A mirror, not a merge: a stale file left behind from a previous build is exactly the
        # thing that makes a static site serve a mix of two versions.
        target = Path(args.deploy).expanduser()
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(out, target)
        print(f"deployed -> {target}")

    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"built {out}")
    for p in sorted(out.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(out)!s:<28} {p.stat().st_size / 1024:>8.1f} KB")
    print(f"  {'TOTAL':<28} {total / 1024:>8.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

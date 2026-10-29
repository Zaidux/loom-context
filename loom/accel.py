"""Automatic backend selection: run the Rust port when it is worth it.

The Python implementation is fast enough for normal prompts, but a long
session is hundreds of kilobytes and re-rendering it every turn shows up in
latency. In-process, ``loom-rs`` is ~20x faster on the 113k-token benchmark;
end-to-end through a subprocess (what this module does) it is ~8x at 32k
words, because process startup is included.

The catch is process startup: spawning the binary costs a couple of
milliseconds, which is *more* than Python needs for a small document. So the
rule is deliberately conservative:

1. Force Python if the caller asked for it, or if the input is below
   ``min_words`` (default 4,000 words).
2. Otherwise, probe the binary once (parse a tiny document, with a timeout)
   and remember the result. A hung or missing binary means Python.
3. Run the Rust path. If it fails for any reason, fall back to Python rather
   than lose the request.

Crossover measured by ``bench/backend.py`` on a real session shape is ~2,000
words for row-heavy tables (~0.7x at 1k, 2.2x at 4k, ~8x at 32k) and much
higher for plain prose. 4,000 is the
conservative default: it avoids paying spawn cost on ordinary prompts while
keeping the fast path for actual long sessions, which are the ones where it
matters.

Set ``LOOM_RS`` to point at another build, and ``LOOM_AUTO_MIN_WORDS`` to
change the threshold.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .decompile import decompile
from .parser import parse
from .render import render

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT / "rust" / "target" / "release" / "loom-rs"
DEFAULT_MIN_WORDS = 4_000
PROBE_SOURCE = "@loom 1.0\n!goal probe\n#state\n  ok = true\n"
PROBE_TIMEOUT = 0.35

#: (path, mtime) -> milliseconds, or None when the probe failed.
_PROBE_CACHE: dict[tuple[str, float], float | None] = {}


class RustError(RuntimeError):
    """The Rust binary was unavailable, timed out, or rejected the input."""


@dataclass(frozen=True)
class BackendDecision:
    """Why a particular backend was chosen. Printed by ``--explain``."""

    backend: str
    words: int
    threshold: int
    probe_ms: float | None
    reason: str
    requested: str = "auto"

    def describe(self) -> str:
        probe = "n/a" if self.probe_ms is None else f"{self.probe_ms:.2f} ms"
        return (
            f"backend={self.backend} words={self.words} threshold={self.threshold} "
            f"probe={probe} ({self.reason})"
        )


def word_count(text: str) -> int:
    """Cheap size signal. Whitespace splitting avoids tokenising big inputs."""
    return len(text.split())


def find_binary(path: str | os.PathLike[str] | None = None) -> Path | None:
    """Locate ``loom-rs``: explicit path, ``$LOOM_RS``, repo build, then ``$PATH``.

    An explicit path is authoritative: if it does not point at an executable we
    report the binary as missing rather than silently using a different build.
    """
    if path:
        p = Path(path).expanduser()
        return p if p.is_file() and os.access(p, os.X_OK) else None
    candidates = [os.environ.get("LOOM_RS"), DEFAULT_BINARY]
    for candidate in candidates:
        if not candidate:
            continue
        p = Path(candidate).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p
    found = shutil.which("loom-rs")
    return Path(found) if found else None


def probe_rust(
    binary: str | os.PathLike[str] | None = None,
    timeout: float = PROBE_TIMEOUT,
) -> float | None:
    """Round-trip a tiny document through the binary. Returns milliseconds.

    ``None`` means "do not use Rust": missing, not executable, hung past
    ``timeout``, or returned a non-zero status. Results are cached per build so
    repeated calls in a session pay the probe cost once.
    """
    exe = find_binary(binary)
    if exe is None:
        return None
    key = (str(exe), exe.stat().st_mtime)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [str(exe), "parse", "-"],
            input=PROBE_SOURCE,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        _PROBE_CACHE[key] = None
        return None
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    ok = proc.returncode == 0 and proc.stdout.startswith("ok:")
    _PROBE_CACHE[key] = elapsed_ms if ok else None
    return _PROBE_CACHE[key]


def default_min_words() -> int:
    raw = os.environ.get("LOOM_AUTO_MIN_WORDS")
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_MIN_WORDS


def choose_backend(
    text: str,
    *,
    backend: str = "auto",
    min_words: int | None = None,
    binary: str | os.PathLike[str] | None = None,
    probe_timeout: float = PROBE_TIMEOUT,
) -> BackendDecision:
    """Decide between ``python`` and ``rust`` for this input."""
    words = word_count(text)
    threshold = default_min_words() if min_words is None else max(0, min_words)

    if backend not in ("auto", "python", "rust"):
        raise ValueError(f"unknown backend: {backend!r}")
    if backend == "python":
        return BackendDecision("python", words, threshold, None, "forced python", backend)

    # Small inputs: spawn cost exceeds any parse/render saving.
    if backend == "auto" and words < threshold:
        return BackendDecision(
            "python",
            words,
            threshold,
            None,
            f"below threshold ({words} < {threshold} words)",
            backend,
        )

    probe_ms = probe_rust(binary, timeout=probe_timeout)
    if probe_ms is None:
        return BackendDecision(
            "python",
            words,
            threshold,
            None,
            "loom-rs missing or unresponsive; using python",
            backend,
        )
    reason = (
        f"rust requested explicitly ({words} < {threshold} words)"
        if backend == "rust" and words < threshold
        else f"large input ({words} >= {threshold} words) and loom-rs responded"
    )
    return BackendDecision("rust", words, threshold, probe_ms, reason, backend)


def run_rust(
    binary: str | os.PathLike[str] | None,
    command: str,
    source: str,
    *,
    timeout: float,
    extra: list[str] | None = None,
) -> str:
    exe = find_binary(binary)
    if exe is None:
        raise RustError("loom-rs not found")
    try:
        proc = subprocess.run(
            [str(exe), command, "-", *(extra or [])],
            input=source,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RustError(str(exc)) from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise RustError(detail[-1] if detail else f"exit {proc.returncode}")
    return proc.stdout


def render_source(
    source: str,
    *,
    budget: int | None = None,
    order: str = "salient",
    recap: bool = False,
    legend: bool = False,
    backend: str = "auto",
    min_words: int | None = None,
    binary: str | os.PathLike[str] | None = None,
    timeout: float = 30.0,
    probe_timeout: float = PROBE_TIMEOUT,
) -> tuple[str, BackendDecision]:
    """Render Loom source, using Rust when the detector says it is safe.

    Falls back to Python if the Rust process fails after being selected: a
    backend optimisation must never turn a renderable document into an error.
    """
    decision = choose_backend(
        source,
        backend=backend,
        min_words=min_words,
        binary=binary,
        probe_timeout=probe_timeout,
    )
    if decision.backend == "rust":
        extra: list[str] = []
        if budget is not None:
            extra += ["-b", str(budget)]
        if order == "chrono":
            extra.append("--chrono")
        if recap:
            extra.append("--recap")
        if legend:
            extra.append("--legend")
        try:
            return run_rust(binary, "render", source, timeout=timeout, extra=extra), decision
        except RustError as exc:
            decision = BackendDecision(
                "python",
                decision.words,
                decision.threshold,
                decision.probe_ms,
                f"rust failed ({exc}); fell back to python",
                decision.requested,
            )

    doc = parse(source)
    text = render(doc, budget=budget, order=order, recap=recap, legend=legend)
    return text, decision


def decompile_source(
    source: str,
    *,
    backend: str = "auto",
    min_words: int | None = None,
    binary: str | os.PathLike[str] | None = None,
    timeout: float = 30.0,
    probe_timeout: float = PROBE_TIMEOUT,
) -> tuple[str, BackendDecision]:
    """Decompile Loom source to English, with the same detector/fallback rule."""
    decision = choose_backend(
        source,
        backend=backend,
        min_words=min_words,
        binary=binary,
        probe_timeout=probe_timeout,
    )
    if decision.backend == "rust":
        try:
            return run_rust(binary, "decompile", source, timeout=timeout), decision
        except RustError as exc:
            decision = BackendDecision(
                "python",
                decision.words,
                decision.threshold,
                decision.probe_ms,
                f"rust failed ({exc}); fell back to python",
                decision.requested,
            )

    return decompile(parse(source)), decision


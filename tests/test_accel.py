"""Tests for automatic backend selection and the Rust bridge."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from loom import (
    BackendDecision,
    LoomSyntaxError,
    choose_backend,
    decompile,
    find_binary,
    parse,
    probe_rust,
    render,
    render_source,
    decompile_source,
)
from loom.accel import DEFAULT_BINARY

ROOT = Path(__file__).resolve().parents[1]
AUTH = (ROOT / "examples" / "auth_refresh.loom").read_text()

rust_required = pytest.mark.skipif(
    not DEFAULT_BINARY.exists(), reason="loom-rs not built (cd rust && cargo build --release)"
)


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def test_small_input_never_spawns_rust():
    decision = choose_backend(AUTH, min_words=10_000)
    assert decision.backend == "python"
    assert decision.probe_ms is None
    assert "below threshold" in decision.reason


def test_forced_python_skips_the_probe():
    decision = choose_backend(AUTH, backend="python", min_words=0)
    assert decision.backend == "python"
    assert "forced" in decision.reason


def test_env_var_sets_the_threshold(monkeypatch):
    monkeypatch.setenv("LOOM_AUTO_MIN_WORDS", "5")
    decision = choose_backend(AUTH, binary=Path("/nonexistent"))
    assert decision.threshold == 5
    # threshold reached but the explicit binary is missing, so Python wins
    assert decision.backend == "python"
    assert "missing" in decision.reason or "unresponsive" in decision.reason


def test_bad_env_value_is_ignored(monkeypatch):
    monkeypatch.setenv("LOOM_AUTO_MIN_WORDS", "not-a-number")
    assert choose_backend(AUTH).threshold == 4000


def test_missing_binary_falls_back(tmp_path):
    decision = choose_backend(AUTH, backend="rust", binary=tmp_path / "nope")
    assert decision.backend == "python"
    assert "missing" in decision.reason


def test_explicit_path_does_not_fall_back_to_repo_build(tmp_path):
    assert find_binary(tmp_path / "nope") is None


def test_slow_binary_fails_the_probe(tmp_path):
    slow = _script(tmp_path, "slow.sh", "sleep 5\n")
    assert probe_rust(slow, timeout=0.1) is None
    decision = choose_backend(AUTH, backend="rust", binary=slow, probe_timeout=0.1)
    assert decision.backend == "python"
    assert "unresponsive" in decision.reason


def test_broken_binary_fails_the_probe(tmp_path):
    broken = _script(tmp_path, "broken.sh", "exit 7\n")
    assert probe_rust(broken) is None


def test_probe_is_cached_per_build(tmp_path):
    counter = tmp_path / "counter"
    script = _script(
        tmp_path,
        "count.sh",
        f'echo x >> "{counter}"\necho "ok: 0 sections, 0 rows, 0 rules"\n',
    )
    assert probe_rust(script) is not None
    assert probe_rust(script) is not None
    assert counter.read_text().count("x") == 1


def test_rust_failure_falls_back_to_python(tmp_path):
    # responds to the probe, then rejects every render
    script = _script(
        tmp_path,
        "parse_only.sh",
        'if [ "$1" = "parse" ]; then echo "ok: 0 sections"; exit 0; fi\necho "cannot render" >&2\nexit 3\n',
    )
    text, decision = render_source(AUTH, backend="rust", binary=script)
    assert decision.backend == "python"
    assert "fell back" in decision.reason
    assert text == render(parse(AUTH))


def test_render_source_uses_python_when_told_to():
    text, decision = render_source(AUTH, backend="python")
    assert decision.backend == "python"
    assert text == render(parse(AUTH))


@rust_required
def test_rust_render_matches_python():
    text, decision = render_source(AUTH, backend="rust")
    assert decision.backend == "rust"
    assert decision.probe_ms is not None
    assert text == render(parse(AUTH))


@rust_required
def test_rust_decompile_matches_python():
    text, decision = decompile_source(AUTH, backend="rust")
    assert decision.backend == "rust"
    assert text == decompile(parse(AUTH))


@rust_required
def test_auto_selects_rust_above_threshold():
    decision = choose_backend(AUTH, min_words=0)
    assert decision.backend == "rust"
    assert decision.probe_ms is not None


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError):
        choose_backend(AUTH, backend="wasm")


def test_decision_describe_is_readable():
    d = BackendDecision("python", 12, 4000, None, "below threshold")
    assert "backend=python" in d.describe()
    assert "threshold=4000" in d.describe()


def test_render_source_still_reports_syntax_errors():
    with pytest.raises(LoomSyntaxError):
        render_source("#evidence{id,src}\n  one-cell\n", backend="python")


@rust_required
def test_cli_explains_the_backend(capsys):
    from loom.cli import main

    assert main(["render", str(ROOT / "examples" / "auth_refresh.loom"), "--explain"]) == 0
    captured = capsys.readouterr()
    assert "backend=" in captured.err
    assert captured.out.startswith("@loom")


def test_cli_stats_reports_backend(tmp_path, capsys):
    from loom.cli import main

    f = tmp_path / "x.loom"
    f.write_text(AUTH)
    assert main(["render", str(f), "--backend", "python", "--stats"]) == 0
    err = capsys.readouterr().err
    assert '"backend": "python"' in err


def test_output_bench_measures_both_directions():
    from bench.output import measure

    source = (ROOT / "examples" / "migration_english.md").read_text()
    row = measure(source)
    assert row["english"] > 0
    assert row["lossless"] > 0
    assert row["lossy"] <= row["lossless"]
    assert row["decode"] > 0
    assert 0 <= row["lossy_fidelity_pct"] <= 100

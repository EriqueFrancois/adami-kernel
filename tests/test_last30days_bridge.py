import sys
from pathlib import Path

import pytest

from adami_kernel.integration.last30days_bridge import run_last30days


def _write_fake_last30days(tmp_path: Path) -> Path:
    """
    A tiny fake CLI that mimics:
      python fake.py <topic> --emit=... --sources=... [--refresh]
    """
    p = tmp_path / "fake_last30days.py"
    p.write_text(
        """
import argparse, json, os, sys, time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("topic")
parser.add_argument("--emit", default="compact")
parser.add_argument("--sources", default="auto")
parser.add_argument("--refresh", action="store_true")
args = parser.parse_args()

if os.environ.get("FAKE_SLEEP_SEC"):
    time.sleep(float(os.environ["FAKE_SLEEP_SEC"]))

if os.environ.get("FAKE_EXIT_CODE"):
    sys.stderr.write("boom\\n")
    raise SystemExit(int(os.environ["FAKE_EXIT_CODE"]))

emit = args.emit

if emit == "json":
    print(json.dumps({"topic": args.topic, "sources": args.sources, "refresh": args.refresh}))
elif emit == "path":
    out = os.environ.get("FAKE_OUT_PATH")
    if not out:
        raise SystemExit(2)
    Path(out).write_text(f"CTX:{args.topic}", encoding="utf-8")
    print(out)
else:
    print(f"EMIT:{emit} TOPIC:{args.topic} SOURCES:{args.sources} REFRESH:{args.refresh}")
""".lstrip(),
        encoding="utf-8",
    )
    return p


@pytest.mark.asyncio
async def test_bridge_emit_json_parses(tmp_path: Path) -> None:
    script = _write_fake_last30days(tmp_path)
    r = await run_last30days(
        "hello",
        emit="json",
        sources="reddit",
        refresh=True,
        timeout=2.0,
        script_path=str(script),
        python_executable=sys.executable,
        enable_cache=False,
    )
    assert r["ok"] is True
    assert r["exit_code"] == 0
    assert isinstance(r["parsed"], dict)
    assert r["parsed"]["topic"] == "hello"
    assert r["parsed"]["sources"] == "reddit"
    assert r["parsed"]["refresh"] is True


@pytest.mark.asyncio
async def test_bridge_emit_context_returns_text(tmp_path: Path) -> None:
    script = _write_fake_last30days(tmp_path)
    r = await run_last30days(
        "t1",
        emit="context",
        sources="auto",
        refresh=False,
        timeout=2.0,
        script_path=str(script),
        python_executable=sys.executable,
        enable_cache=False,
    )
    assert r["ok"] is True
    assert "TOPIC:t1" in r["parsed"]


@pytest.mark.asyncio
async def test_bridge_emit_path_reads_file(tmp_path: Path) -> None:
    script = _write_fake_last30days(tmp_path)
    out_path = tmp_path / "out.txt"
    r = await run_last30days(
        "t2",
        emit="path",
        sources="x",
        refresh=False,
        timeout=2.0,
        script_path=str(script),
        python_executable=sys.executable,
        env={"FAKE_OUT_PATH": str(out_path)},
        enable_cache=False,
        read_path_output=True,
    )
    assert r["ok"] is True
    assert r["output_paths"] == [str(out_path)]
    assert r["parsed"] == "CTX:t2"


@pytest.mark.asyncio
async def test_bridge_timeout(tmp_path: Path) -> None:
    script = _write_fake_last30days(tmp_path)
    r = await run_last30days(
        "slow",
        emit="context",
        sources="auto",
        refresh=False,
        timeout=0.1,
        script_path=str(script),
        python_executable=sys.executable,
        env={"FAKE_SLEEP_SEC": "1.0"},
        enable_cache=False,
    )
    assert r["ok"] is False
    assert r["error"]["kind"] == "timeout"


@pytest.mark.asyncio
async def test_bridge_script_missing() -> None:
    r = await run_last30days(
        "x",
        emit="context",
        sources="auto",
        refresh=False,
        timeout=1.0,
        script_path="/no/such/last30days.py",
        python_executable=sys.executable,
        enable_cache=False,
    )
    assert r["ok"] is False
    assert r["error"]["kind"] in ("script_not_found", "script_path_missing")


@pytest.mark.asyncio
async def test_bridge_cache_hit(tmp_path: Path) -> None:
    script = _write_fake_last30days(tmp_path)
    r1 = await run_last30days(
        "cacheme",
        emit="context",
        sources="auto",
        refresh=False,
        timeout=2.0,
        script_path=str(script),
        python_executable=sys.executable,
        enable_cache=True,
        cache_ttl_sec=30.0,
    )
    r2 = await run_last30days(
        "cacheme",
        emit="context",
        sources="auto",
        refresh=False,
        timeout=2.0,
        script_path=str(script),
        python_executable=sys.executable,
        enable_cache=True,
        cache_ttl_sec=30.0,
    )
    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r2["cache_hit"] is True

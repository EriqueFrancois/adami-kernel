"""模块四步骤 6：DeerFlow 侧车桥（配置校验、HTTP Mock、CLI）。"""

import sys
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from adami_kernel.config import settings
from adami_kernel.integration import deer_flow_bridge as df
from adami_kernel.integration.deer_flow_bridge import (
    DeerFlowBridge,
    DeerFlowBridgeConfigError,
    build_deerflow_bridge_for_tests,
    stage_artifact_for_deerflow_delegate,
    validate_deerflow_base_url,
)


def test_validate_rejects_bind_all_host(monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_REJECT_INSECURE_BIND_HOSTS", True)
    with pytest.raises(DeerFlowBridgeConfigError, match="0.0.0.0"):
        validate_deerflow_base_url("http://0.0.0.0:8080/api")


def test_validate_https_ok():
    u = validate_deerflow_base_url("https://deerflow.internal.example/path/")
    assert u == "https://deerflow.internal.example/path"


def test_validate_http_only_loopback(monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_ALLOW_HTTP_LOCALHOST", True)
    assert validate_deerflow_base_url("http://127.0.0.1:9").endswith(":9")
    with pytest.raises(DeerFlowBridgeConfigError, match="loopback"):
        validate_deerflow_base_url("http://10.0.0.1:9")


def test_validate_allowed_hosts(monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_ALLOWED_HOSTS", ["df.corp"])
    with pytest.raises(DeerFlowBridgeConfigError, match="not in ADAMI_DEERFLOW_ALLOWED_HOSTS"):
        validate_deerflow_base_url("https://other.example")
    assert validate_deerflow_base_url("https://df.corp").startswith("https://df.corp")


def test_require_token_blocks_http(monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_REQUIRE_TOKEN", True)
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_TOKEN", "")
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_BASE_URL", "https://df.example")
    with pytest.raises(DeerFlowBridgeConfigError, match="TOKEN"):
        df._require_http_auth_if_configured()


def test_stage_artifact_maps_result():
    art = stage_artifact_for_deerflow_delegate(
        task_id="t1",
        result={"summary": "S", "artifacts": [{"uri": "https://a/x"}]},
    )
    assert art.artifact_type == "deerflow_delegate"
    assert art.uri_or_payload_ref == "https://a/x"
    assert "S" in art.summary


@pytest.mark.asyncio
async def test_http_submit_poll_result_mock_transport(monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_REQUIRE_TOKEN", False)
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_POLL_INTERVAL_SEC", 0.05)

    n_status = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if request.method == "POST" and "submit" in u:
            return httpx.Response(200, json={"task_id": "job-a"})
        if request.method == "GET" and "status" in u:
            n_status["i"] += 1
            if n_status["i"] < 2:
                return httpx.Response(200, json={"state": "running"})
            return httpx.Response(200, json={"state": "completed"})
        if request.method == "GET" and "result" in u:
            return httpx.Response(200, json={"summary": "done", "artifacts": []})
        return httpx.Response(404, text=u)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:1")
    bridge = build_deerflow_bridge_for_tests(client)
    tid = await bridge.submit(workflow_id="wf", chat_id="c", prompt="hello", metadata={})
    assert tid == "job-a"
    out = await bridge.run_until_done(tid, poll_timeout_sec=5.0)
    assert out["summary"] == "done"
    await client.aclose()


@pytest.mark.asyncio
async def test_cli_roundtrip(tmp_path, monkeypatch):
    cli = tmp_path / "df_cli.py"
    body = """
import json, sys
op = sys.argv[1]
raw = sys.stdin.read()
req = json.loads(raw) if raw.strip() else {}
if op == "submit":
    print(json.dumps({"task_id": "cli-task"}))
elif op == "status":
    print(json.dumps({"state": "completed"}))
elif op == "result":
    print(json.dumps({"summary": "from-cli", "artifacts": []}))
else:
    print("{}")
"""
    cli.write_text(f"#!{sys.executable}\n{body}")
    cli.chmod(0o700)
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_BASE_URL", "")
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_CLI_PATH", str(cli))

    b = DeerFlowBridge()
    tid = await b.submit(workflow_id="w", chat_id="c", prompt="p")
    assert tid == "cli-task"
    res = await b.run_until_done(tid, poll_timeout_sec=3.0)
    assert res["summary"] == "from-cli"


@pytest.mark.asyncio
async def test_execute_delegate_writes_context_and_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_LONG_TASK_TRACKING_ENABLED", True)
    mem = MagicMock()
    mem.save_workflow_state = AsyncMock()
    from adami_kernel.orchestrator.long_task_schema import parse_stage_artifacts_from_context
    from adami_kernel.orchestrator.workflow_models import Node, WorkflowState

    st = WorkflowState(
        chat_id="cx",
        workflow_id="wf_df",
        metadata={"long_task_tracking_enabled": True},
        nodes={
            "n1": Node(
                node_id="n1",
                node_type="DELEGATE_DEERFLOW",
                config={"prompt": "do research"},
            ),
        },
        edges={"n1": []},
        current_node_id="n1",
        context={"long_task_stages": []},
    )

    class FB:
        def __init__(self, http_client=None):
            pass

        async def submit(self, **kw):
            return "ext-1"

        async def run_until_done(self, task_id, poll_timeout_sec):
            return {"summary": "e2e", "artifacts": [{"uri": "deerflow://x"}]}

    monkeypatch.setattr(df, "DeerFlowBridge", FB)
    out = await df.execute_delegate_deerflow_node(
        memory=mem,
        state=st,
        node_id="n1",
        resolve_prompt=lambda s: s,
        poll_timeout_sec=30.0,
    )
    assert out["status"] == "success"
    assert st.context["n1"]["task_id"] == "ext-1"
    arts = parse_stage_artifacts_from_context(st.context)
    assert any(a.artifact_type == "deerflow_delegate" for a in arts)
    mem.save_workflow_state.assert_awaited()

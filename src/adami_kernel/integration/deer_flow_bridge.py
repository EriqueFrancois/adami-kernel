"""
外部 DeerFlow 侧车桥（模块四 · 步骤 6）

- 不导入、不依赖 deer-flow Python 包；仅通过 **HTTP** 或 **CLI 子进程** 与已部署实例交互。
- 契约：提交子任务 → 轮询状态 → 拉回结果 JSON；由 AdamI 映射为 `StageArtifact`。

HTTP 默认路径（可通过 `ADAMI_DEERFLOW_*` 覆盖）::

    POST {BASE}{ADAMI_DEERFLOW_SUBMIT_PATH}
        body: {"workflow_id","chat_id","prompt","metadata"?}
        resp: {"task_id": "..."} 或 {"id": "..."}

    GET {BASE}{ADAMI_DEERFLOW_STATUS_PATH_TEMPLATE}
        resp: {"state"|"status": "pending|running|completed|failed|..." , "error"?}

    GET {BASE}{ADAMI_DEERFLOW_RESULT_PATH_TEMPLATE}
        resp: {"summary"?, "output_text"?, "artifacts"?: [{"uri"|"url","label"?}], ...}

CLI 模式（`ADAMI_DEERFLOW_CLI_PATH` 非空且未配置 BASE_URL）::

    每次调用: ``<cli> <submit|status|result>`` ，stdin 为一行 JSON，stdout 为一行 JSON。
    ``<cli>`` 须为**可执行文件**（带 shebang 的脚本或二进制）；裸 ``.py`` 文件需 ``#!/path/to/python`` 或改用 shell 包装。

安全见 `docs/deer_flow_bridge_security.md`（步骤 6.1）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.orchestrator.long_task_schema import (
    LongTaskPhase,
    StageArtifact,
    append_stage_artifact,
    is_long_task_tracking_enabled,
)
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState

logger = logging.getLogger("AdamI-DeerFlowBridge")


def _dfb_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class DeerFlowBridgeError(RuntimeError):
    """侧车调用失败（网络、协议、远端错误）。"""


class DeerFlowBridgeConfigError(DeerFlowBridgeError):
    """配置不合法或违反安全策略。"""


_TERMINAL_OK = frozenset({"completed", "complete", "success", "done", "succeeded"})
_TERMINAL_BAD = frozenset({"failed", "error", "cancelled", "canceled"})


def deer_flow_delegate_enabled_for_execution() -> bool:
    """是否允许执行 DELEGATE_DEERFLOW 节点（显式总闸）。"""
    return bool(getattr(settings, "ADAMI_DEERFLOW_ENABLED", False))


def validate_deerflow_base_url(url: str) -> str:
    """
    校验 BASE_URL：拒绝空 host、全网绑定地址；http 仅允许 loopback（可关）。
    返回去掉末尾 / 的 base URL。
    """
    raw = (url or "").strip()
    if not raw:
        raise DeerFlowBridgeConfigError("ADAMI_DEERFLOW_BASE_URL is empty")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not host:
        raise DeerFlowBridgeConfigError("DeerFlow URL must include a host")
    if getattr(settings, "ADAMI_DEERFLOW_REJECT_INSECURE_BIND_HOSTS", True):
        if host in ("0.0.0.0", "::", "[::]"):
            raise DeerFlowBridgeConfigError(
                f"Refusing DeerFlow URL host {host!r}: use 127.0.0.1, localhost, "
                "or an explicit internal hostname — not a bind-all address."
            )
    scheme = (parsed.scheme or "").lower()
    if scheme == "https":
        pass
    elif scheme == "http":
        if not getattr(settings, "ADAMI_DEERFLOW_ALLOW_HTTP_LOCALHOST", True):
            raise DeerFlowBridgeConfigError(
                "HTTP not allowed for DeerFlow (use https or enable "
                "ADAMI_DEERFLOW_ALLOW_HTTP_LOCALHOST for loopback only)"
            )
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise DeerFlowBridgeConfigError(
                "HTTP only allowed for loopback hosts (127.0.0.1, localhost, ::1)"
            )
    else:
        raise DeerFlowBridgeConfigError(
            f"Unsupported URL scheme {scheme!r}; use https or http (loopback only)"
        )
    allow = list(getattr(settings, "ADAMI_DEERFLOW_ALLOWED_HOSTS", None) or [])
    if allow:
        allowed = {str(x).strip().lower() for x in allow if str(x).strip()}
        if host not in allowed:
            raise DeerFlowBridgeConfigError(
                f"Host {host!r} not in ADAMI_DEERFLOW_ALLOWED_HOSTS={sorted(allowed)!r}"
            )
    return raw.rstrip("/")


def _require_http_auth_if_configured() -> None:
    if (
        getattr(settings, "ADAMI_DEERFLOW_REQUIRE_TOKEN", False)
        and not (getattr(settings, "ADAMI_DEERFLOW_TOKEN", None) or "").strip()
    ):
        raise DeerFlowBridgeConfigError(
            "ADAMI_DEERFLOW_REQUIRE_TOKEN is true but ADAMI_DEERFLOW_TOKEN is empty"
        )


def _extract_task_id(data: Dict[str, Any]) -> str:
    for k in ("task_id", "id", "job_id", "run_id"):
        v = data.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    raise DeerFlowBridgeError(f"submit response missing task id: {data!r}")


def _normalize_status_payload(data: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    st = data.get("state") or data.get("status") or ""
    st_l = str(st).lower().strip()
    err = data.get("error") or data.get("message")
    return st_l, str(err) if err is not None else None


def _httpx_verify_and_cert() -> Tuple[Any, Optional[Tuple[str, str]]]:
    ca = getattr(settings, "ADAMI_DEERFLOW_TLS_CA_FILE", None)
    verify: Any = ca if ca and str(ca).strip() else True
    cf = getattr(settings, "ADAMI_DEERFLOW_TLS_CLIENT_CERT_FILE", None)
    kf = getattr(settings, "ADAMI_DEERFLOW_TLS_CLIENT_KEY_FILE", None)
    cs = (cf or "").strip()
    ks = (kf or "").strip()
    if cs and ks:
        return verify, (cs, ks)
    if cs or ks:
        raise DeerFlowBridgeConfigError(
            "mTLS requires both ADAMI_DEERFLOW_TLS_CLIENT_CERT_FILE and "
            "ADAMI_DEERFLOW_TLS_CLIENT_KEY_FILE"
        )
    return verify, None


def stage_artifact_for_deerflow_delegate(
    *,
    task_id: str,
    result: Dict[str, Any],
) -> StageArtifact:
    """将侧车结果映射为 AdamI `StageArtifact`（大内容走 uri，摘要进 summary）。"""
    uri: Optional[str] = None
    arts = result.get("artifacts")
    if isinstance(arts, list) and arts:
        first = arts[0]
        if isinstance(first, dict):
            uri = first.get("uri") or first.get("url")
    if not uri:
        uri = f"deerflow://task/{task_id}"
    summary_bits: list[str] = []
    for k in ("summary", "output_text", "text"):
        v = result.get(k)
        if isinstance(v, str) and v.strip():
            summary_bits.append(v.strip())
            break
    summary = "\n".join(summary_bits)[:8192]
    return StageArtifact(
        phase=LongTaskPhase.RESEARCH,
        artifact_type="deerflow_delegate",
        uri_or_payload_ref=uri[:2048] if uri else None,
        summary=summary,
        producer_agent="integration.deer_flow_bridge",
        content_hash=None,
    )


class DeerFlowBridge:
    """HTTP 或 CLI 薄客户端；不缓存长连接跨进程（每次委托可新建 client）。"""

    def __init__(self, *, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._external_client = http_client
        self._mode = self._resolve_mode()

    def _resolve_mode(self) -> str:
        base = (getattr(settings, "ADAMI_DEERFLOW_BASE_URL", None) or "").strip()
        cli = (getattr(settings, "ADAMI_DEERFLOW_CLI_PATH", None) or "").strip()
        if base:
            return "http"
        if cli:
            return "cli"
        raise DeerFlowBridgeConfigError(
            "ADAMI_DEERFLOW_ENABLED requires ADAMI_DEERFLOW_BASE_URL or ADAMI_DEERFLOW_CLI_PATH"
        )

    def _base_url(self) -> str:
        return validate_deerflow_base_url(getattr(settings, "ADAMI_DEERFLOW_BASE_URL", "") or "")

    def _headers(self) -> Dict[str, str]:
        tok = (getattr(settings, "ADAMI_DEERFLOW_TOKEN", None) or "").strip()
        h: Dict[str, str] = {"Accept": "application/json", "Content-Type": "application/json"}
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        return h

    async def _cli_json(self, op: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        exe = (getattr(settings, "ADAMI_DEERFLOW_CLI_PATH", None) or "").strip()
        if not exe:
            raise DeerFlowBridgeConfigError("ADAMI_DEERFLOW_CLI_PATH not set")
        p = Path(exe).expanduser()
        if not p.is_file():
            raise DeerFlowBridgeConfigError(f"ADAMI_DEERFLOW_CLI_PATH is not a file: {exe!r}")
        proc = await asyncio.create_subprocess_exec(
            str(p),
            op,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await proc.communicate(json.dumps(payload).encode("utf-8"))
        if proc.returncode != 0:
            err_t = err_b.decode(errors="replace").strip()
            logger.error(_dfb_t("dfb.err.cli", op=op, rc=proc.returncode, err=err_t))
            raise DeerFlowBridgeError(
                f"DeerFlow CLI {op} exit {proc.returncode}: {err_t or out_b.decode(errors='replace')}"
            )
        try:
            line = out_b.decode("utf-8").strip().splitlines()[-1] if out_b.strip() else "{}"
            return json.loads(line)
        except json.JSONDecodeError as e:
            raise DeerFlowBridgeError(f"DeerFlow CLI {op} invalid JSON: {e}") from e

    async def submit(
        self,
        *,
        workflow_id: str,
        chat_id: str,
        prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        body: Dict[str, Any] = {
            "workflow_id": workflow_id,
            "chat_id": chat_id,
            "prompt": prompt,
            "metadata": metadata or {},
        }
        if self._mode == "cli":
            data = await self._cli_json("submit", body)
            return _extract_task_id(data)

        _require_http_auth_if_configured()
        base = self._base_url()
        path = getattr(settings, "ADAMI_DEERFLOW_SUBMIT_PATH", "/api/adami/v1/delegate/submit")
        url = f"{base}{path}"
        timeout = float(getattr(settings, "ADAMI_DEERFLOW_HTTP_TIMEOUT_SEC", 30.0))
        verify, cert = _httpx_verify_and_cert()
        client = self._external_client
        close_after = False
        if client is None:
            client = httpx.AsyncClient(
                verify=verify,
                cert=cert,
                timeout=timeout,
                follow_redirects=False,
            )
            close_after = True
        try:
            r = await client.post(url, headers=self._headers(), json=body)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise DeerFlowBridgeError(f"submit: expected JSON object, got {type(data)}")
            return _extract_task_id(data)
        except httpx.HTTPError as e:
            logger.error(_dfb_t("dfb.err.submit_http", e=e))
            raise DeerFlowBridgeError(f"DeerFlow submit failed: {e}") from e
        finally:
            if close_after and client is not None:
                await client.aclose()

    async def fetch_status(self, task_id: str) -> Tuple[str, Optional[str]]:
        if self._mode == "cli":
            data = await self._cli_json("status", {"task_id": task_id})
            if not isinstance(data, dict):
                raise DeerFlowBridgeError("status: expected JSON object")
            return _normalize_status_payload(data)

        _require_http_auth_if_configured()
        base = self._base_url()
        tmpl = getattr(
            settings,
            "ADAMI_DEERFLOW_STATUS_PATH_TEMPLATE",
            "/api/adami/v1/delegate/tasks/{task_id}/status",
        )
        path = tmpl.format(task_id=task_id)
        url = f"{base}{path}"
        timeout = float(getattr(settings, "ADAMI_DEERFLOW_HTTP_TIMEOUT_SEC", 30.0))
        verify, cert = _httpx_verify_and_cert()
        client = self._external_client
        close_after = False
        if client is None:
            client = httpx.AsyncClient(
                verify=verify,
                cert=cert,
                timeout=timeout,
                follow_redirects=False,
            )
            close_after = True
        try:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise DeerFlowBridgeError(f"status: expected JSON object, got {type(data)}")
            return _normalize_status_payload(data)
        except httpx.HTTPError as e:
            logger.error(_dfb_t("dfb.err.status_http", e=e))
            raise DeerFlowBridgeError(f"DeerFlow status failed: {e}") from e
        finally:
            if close_after and client is not None:
                await client.aclose()

    async def fetch_result(self, task_id: str) -> Dict[str, Any]:
        if self._mode == "cli":
            data = await self._cli_json("result", {"task_id": task_id})
            if not isinstance(data, dict):
                raise DeerFlowBridgeError("result: expected JSON object")
            return data

        _require_http_auth_if_configured()
        base = self._base_url()
        tmpl = getattr(
            settings,
            "ADAMI_DEERFLOW_RESULT_PATH_TEMPLATE",
            "/api/adami/v1/delegate/tasks/{task_id}/result",
        )
        path = tmpl.format(task_id=task_id)
        url = f"{base}{path}"
        timeout = float(getattr(settings, "ADAMI_DEERFLOW_HTTP_TIMEOUT_SEC", 30.0))
        verify, cert = _httpx_verify_and_cert()
        client = self._external_client
        close_after = False
        if client is None:
            client = httpx.AsyncClient(
                verify=verify,
                cert=cert,
                timeout=timeout,
                follow_redirects=False,
            )
            close_after = True
        try:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise DeerFlowBridgeError(f"result: expected JSON object, got {type(data)}")
            return data
        except httpx.HTTPError as e:
            logger.error(_dfb_t("dfb.err.result_http", e=e))
            raise DeerFlowBridgeError(f"DeerFlow result failed: {e}") from e
        finally:
            if close_after and client is not None:
                await client.aclose()

    async def run_until_done(
        self,
        task_id: str,
        *,
        poll_timeout_sec: float,
    ) -> Dict[str, Any]:
        interval = float(getattr(settings, "ADAMI_DEERFLOW_POLL_INTERVAL_SEC", 2.0))
        interval = max(0.05, interval)
        deadline = asyncio.get_event_loop().time() + poll_timeout_sec
        while True:
            st, err = await self.fetch_status(task_id)
            if st in _TERMINAL_BAD:
                raise DeerFlowBridgeError(err or f"DeerFlow task {task_id} status={st!r}")
            if st in _TERMINAL_OK:
                return await self.fetch_result(task_id)
            if asyncio.get_event_loop().time() >= deadline:
                raise DeerFlowBridgeError(
                    f"DeerFlow task {task_id} poll timeout after {poll_timeout_sec}s (last_status={st!r})"
                )
            await asyncio.sleep(interval)


async def execute_delegate_deerflow_node(
    *,
    memory: Any,
    state: WorkflowState,
    node_id: str,
    resolve_prompt: Any,
    poll_timeout_sec: float,
) -> Dict[str, Any]:
    """
    由 WorkflowEngine 调用：提交 → 轮询 → 结果写 context + StageArtifact + 持久化。
    resolve_prompt: Callable[[str], str] 模板解析（引擎的 _resolve_string_template）。
    """
    node = state.nodes[node_id]
    if not isinstance(node, Node):
        raise RuntimeError(f"missing node {node_id}")
    raw_prompt = (node.config.get("prompt") or node.config.get("task") or "").strip()
    if not raw_prompt:
        raise DeerFlowBridgeError("DELEGATE_DEERFLOW node requires config.prompt (or task)")
    prompt = resolve_prompt(raw_prompt)
    bridge = DeerFlowBridge()
    task_id = await bridge.submit(
        workflow_id=state.workflow_id,
        chat_id=state.chat_id,
        prompt=prompt,
        metadata={
            "node_id": node_id,
            "workflow_version": state.version,
        },
    )
    result = await bridge.run_until_done(task_id, poll_timeout_sec=poll_timeout_sec)
    payload = {
        "task_id": task_id,
        "deerflow_result": result,
    }
    state.context[node_id] = payload
    if is_long_task_tracking_enabled(state):
        try:
            append_stage_artifact(
                state,
                stage_artifact_for_deerflow_delegate(task_id=task_id, result=result),
                set_current_phase=False,
            )
        except Exception as ex:
            logger.warning(_dfb_t("dfb.warn.stage_skip", e=ex))
    await memory.save_workflow_state(state)
    return {
        "status": "success",
        "data": payload,
        "exit_code": 0,
    }


def build_deerflow_bridge_for_tests(http_client: httpx.AsyncClient) -> DeerFlowBridge:
    """测试注入共享 MockTransport 客户端。"""
    return DeerFlowBridge(http_client=http_client)

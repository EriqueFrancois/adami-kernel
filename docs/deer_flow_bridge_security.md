# DeerFlow 侧车桥安全与运维（模块四 · 步骤 6.1）

本文档配合 `src/adami_kernel/integration/deer_flow_bridge.py` 使用。桥接层**只做 HTTP/CLI 转发**，不扩大 DeerFlow 本身的攻击面；运维仍需遵循 [bytedance/deer-flow](https://github.com/bytedance/deer-flow) 官方 README 中的安全建议（密钥管理、网络隔离、最小权限等）。

## 1. 总闸与依赖边界

- **`ADAMI_DEERFLOW_ENABLED=false`（默认）**：内核不发起任何 DeerFlow 网络/子进程调用；未包含 `DELEGATE_DEERFLOW` 的工作流与现网行为一致。
- **含 `DELEGATE_DEERFLOW` 的 DAG**：必须在配置中启用 `ADAMI_DEERFLOW_ENABLED`，否则 `prepare_composed_workflow_for_bus` 会**拒绝注册**并抛出明确错误（避免运行到一半才失败）。
- **不安装 deer-flow Python 包**：AdamI 默认依赖树不包含 DeerFlow 仓库；侧车为独立进程/容器。

## 2. 网络与监听面

- **禁止将 AdamI 或 DeerFlow 的监听地址默认配成 `0.0.0.0` / `::` 作为「客户端目标」**：桥接在 `ADAMI_DEERFLOW_REJECT_INSECURE_BIND_HOSTS=true`（默认）时会**拒绝**此类 `ADAMI_DEERFLOW_BASE_URL`，并记录配置错误。请使用 **回环**（`127.0.0.1`）或**明确内网主机名**。
- **生产环境优先 HTTPS**；仅当 `ADAMI_DEERFLOW_ALLOW_HTTP_LOCALHOST=true`（默认）时，允许对 **`127.0.0.1` / `localhost` / `::1`** 使用 `http://`，便于本机联调。
- **主机白名单（可选）**：设置 `ADAMI_DEERFLOW_ALLOWED_HOSTS`（小写主机名列表）后，仅允许连接列表中的主机，防止误配或 DNS 劫持指向意外目标。

## 3. 认证与 mTLS

- **Bearer Token**：将令牌放在环境变量 `ADAMI_DEERFLOW_TOKEN`（勿提交仓库）；请求头为 `Authorization: Bearer …`。
- **强制令牌**：`ADAMI_DEERFLOW_REQUIRE_TOKEN=true` 时，若未配置 `ADAMI_DEERFLOW_TOKEN`，桥接在首次 HTTP 调用前会抛出 **`DeerFlowBridgeConfigError`** 并打日志，**拒绝连接**。
- **mTLS（可选）**：同时配置 `ADAMI_DEERFLOW_TLS_CLIENT_CERT_FILE` 与 `ADAMI_DEERFLOW_TLS_CLIENT_KEY_FILE`；可选 `ADAMI_DEERFLOW_TLS_CA_FILE` 校验服务端证书。仅配其一视为配置错误，桥接拒绝初始化该次请求。

## 4. HTTP 行为

- 客户端 **`follow_redirects=False`**，降低开放重定向与跨站风险。
- 超时：`ADAMI_DEERFLOW_HTTP_TIMEOUT_SEC`（单次请求）、`ADAMI_DEERFLOW_POLL_TIMEOUT_SEC`（整段轮询上限，与节点超时取较大者由引擎封装）。

## 5. 路径与契约

- 默认 REST 形状见 `deer_flow_bridge` 模块文档字符串；若真实 DeerFlow 网关路径不同，仅用环境变量改 **`ADAMI_DEERFLOW_SUBMIT_PATH`**、`**_STATUS_PATH_TEMPLATE**`、`**_RESULT_PATH_TEMPLATE**`，无需改内核代码。
- **CLI 模式**：`ADAMI_DEERFLOW_CLI_PATH` 指向**可执行文件**（非目录）；内核通过子进程 `submit|status|result` 传 JSON，适合内网脚本或本地适配器。

## 6. 错误配置时的预期

| 场景 | 行为 |
|------|------|
| `BASE_URL` 使用 `0.0.0.0` 等全网绑定地址 | `DeerFlowBridgeConfigError`，日志说明改用 loopback 或内网主机 |
| `REQUIRE_TOKEN` 且无 token | `DeerFlowBridgeConfigError` |
| 仅配 client cert 未配 key | `DeerFlowBridgeConfigError` |
| 启用侧车但未设 `BASE_URL` 与 `CLI_PATH` | `DeerFlowBridgeConfigError` |
| 侧车未启动 / 连接被拒 | `DeerFlowBridgeError`，工作流节点失败并按现有重试/恢复策略处理 |

## 7. 与步骤 0 边界的关系

档位 B（外部 DeerFlow）下，**工作流真源仍在 AdamI**（`workflow_id` + `LayeredMemory`）；侧车任务 ID 仅作为执行句柄，应通过 `StageArtifact`（`artifact_type=deerflow_delegate`）与 `context` 中的结构化字段追溯。

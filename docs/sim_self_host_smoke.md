# Sim 自托管最小栈（步骤 3.1）

用于在本地或内网跑起 Sim，接收 AdamI **Webhook 桥** POST 的轨迹批次。具体路由与鉴权以你部署的 Sim 版本为准；本文给最小可复现路径与 **curl** 探针。

## 1. 官方入口

- 仓库：<https://github.com/simstudioai/sim>
- 执行 / Webhook / API：<https://docs.sim.ai/execution>
- Docker 自托管：<https://docs.sim.ai/self-hosting/docker>
- 环境变量：<https://docs.sim.ai/self-hosting/environment-variables>

## 2. Docker Compose（示例）

在 Sim 仓库根目录（以官方文档为准）：

```bash
git clone https://github.com/simstudioai/sim.git && cd sim
docker compose -f docker-compose.prod.yml up -d
```

浏览器打开 `http://localhost:3000`（端口以 compose 为准）。完成管理员注册与登录后，在控制台创建 **Workflow**，并配置 **Webhook** 或 **API** 触发（见 Execution 文档）。

## 3. AdamI 侧配置（与 `config.py` / `.env` 对齐）

- `ADAMI_SIM_TRACE_EXPORT_ENABLED`：须为 `true`，否则无后台 flush，Webhook 不会被调用。
- `ADAMI_SIM_WEBHOOK_ENABLED`：`true` 开启 Sim 桥。
- `ADAMI_SIM_WEBHOOK_URL`：Sim 提供的 Webhook 接收地址。
- `ADAMI_SIM_WEBHOOK_SECRET`：可选；非空时对 **请求体字节** HMAC-SHA256，头 `X-Adami-Signature: sha256=<hex>`。
- `ADAMI_SIM_WORKFLOW_ID`：可选；写入 JSON envelope 的 `workflow_id`。
- `ADAMI_SIM_WEBHOOK_MODE`：`envelope`（默认）或 `ndjson_raw`。

## 4. AdamI POST 契约（envelope 默认）

`Content-Type: application/json; charset=utf-8`

```json
{
  "source": "adami-kernel",
  "schema": "adami_sim_webhook.batch.v1",
  "workflow_id": "<可选>",
  "records": [ { "...ReplayTraceRecordV1..." } ]
}
```

校验 HMAC（若配置了 secret）时，应对 **最终 HTTP body 字节**（与 AdamI 发送的 `content` 一致）计算 SHA256。

## 5. curl 模拟 AdamI（手工关键检测）

将下面 URL 换成你的 Webhook 测试地址；`BODY` 为与上节一致的 JSON 文件路径。

```bash
BODY=./sample_batch.json
SECRET=your_shared_secret
SIG=$(printf '%s' "$(cat "$BODY")" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -sS -X POST "$SIM_WEBHOOK_URL" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "X-Adami-Signature: sha256=$SIG" \
  --data-binary @"$BODY" -w "\nHTTP %{http_code}\n"
```

期望：HTTP **2xx**，且 Sim 侧 **Runs / Logs** 或自建中间层能看到一次请求记录。

## 6. 与步骤 1、2 的关系

- 轨迹仍落盘 `ADAMI_DATA_DIR/traces/eventbus.ndjson`（或 `ADAMI_SIM_TRACE_EXPORT_PATH`）。
- 步骤 2 的 `adami-replay-validate` 仅校验 NDJSON 文件，与 Webhook 无关。

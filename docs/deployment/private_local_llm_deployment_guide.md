## AdamI 私有化部署手册（本地模型集成）

本手册面向 **私有化/离线部署** 场景，覆盖 AdamI 当前已集成的本地模型系列：

- **Ollama（Linux / macOS 通用）**：作为本地 LLM 的“最终兜底”。
- **MLX（macOS 优先）**：在 Apple Silicon 上优先使用本地 MLX 推理，失败时自动降级到 Ollama。

对应实现位置（便于审计与二次开发）：

- Hybrid 路由器：`src/adami_kernel/cortex/router.py`（本地优先 + 云端失败降级本地）
- 本地模型配置项：`src/adami_kernel/config.py`（`OLLAMA_*` / `ADAMI_MLX_*`）
- Ollama 自动启动：`src/adami_kernel/core/boot_manager.py`（可选 auto-start）

---

## 1. 部署目标与推荐拓扑

推荐私有化最小可用拓扑（单机）：

- AdamI Kernel（CLI/Web/Telegram/Discord 可按需启用）
- Ollama（本地推理服务）
- 可选：OTel Collector（将 traces/metrics 汇聚到你的内部可观测平台）

---

## 2. 最小配置（只启用本地 LLM）

在 `.env`（或你的机密管理系统）中设置：

- **启用 Ollama**（默认已启用）：
  - `OLLAMA_ENABLED=true`
  - `OLLAMA_HOST=http://127.0.0.1:11434`
  - `OLLAMA_MODEL=qwen3.5:9b`（示例；请替换为你已拉取的模型）
- **禁用云端 LLM（可选但推荐私有化）**：
  - 不设置任何 `*_API_KEY`
  - 或在路由 provider 配置中不填 `api_key`（路由会自动过滤空 key）

关键说明：

- 即使你配置了云端 LLM，AdamI 的 `HybridLLMRouter` 也会在云端异常时 **立即降级到本地 MLX/Ollama**，避免上层工作流被中断。

---

## 3. Ollama 私有化部署（Linux 推荐 systemd）

### 3.1 安装与启动

在 Ubuntu/Debian（示意）：

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
```

健康检查：

```bash
curl -s http://127.0.0.1:11434/api/version
```

### 3.2 拉取模型

```bash
ollama pull qwen3.5:9b
```

### 3.3 AdamI 与 Ollama 的网络

建议 AdamI 与 Ollama 同机部署时使用 `127.0.0.1`，避免在内网暴露推理端口。

如果必须跨机器访问：

- 只在内网绑定
- 配置 ACL / 防火墙
- 使用反向代理 + mTLS（可选）

---

## 4. MLX 私有化部署（macOS / Apple Silicon）

AdamI 会在 `router.py` 中尝试导入并加载 MLX 模型：

- `ADAMI_MLX_ENABLED=true`
- `ADAMI_MLX_MODEL_PATH=mlx-community/Qwen3.5-9B-MLX-4bit`（默认）

注意事项：

- 仅在 macOS（Darwin）上启用；导入失败或加载失败会自动降级（并将 `mlx_enabled` 置为 False）。
- 高负载时可触发 `unload_mlx_model()` 释放内存（路由内部会在失败时主动尝试释放）。

---

## 5. AdamI Kernel 私有化运行方式（Poetry）

```bash
poetry install
poetry run adami
```

建议生产环境使用：

- 专用用户运行（least privilege）
- 设置 `ADAMI_RUNTIME_PROFILE=production`（容器/生产加固策略）
- 按需开启 OTel 导出（见下一节）

---

## 6. 可观测性（私有化推荐）

AdamI 默认开启 Observability，但默认导出到 Console（不需要外部 Collector）：

- `ADAMI_ENABLE_OBSERVABILITY=true`
- `ADAMI_OTEL_EXPORTER=console`

私有化推荐落地 OTLP gRPC：

- `ADAMI_OTEL_EXPORTER=otlp`
- 配置你的 OTLP endpoint（见 `src/adami_kernel/web/otel.py` 与 `.env.example`）

数据安全：

- trace 采样与脱敏策略已在 `src/adami_kernel/observability/otel_export_policy.py` 落地
- 私有化合规建议：保留脱敏开关开启（`ADAMI_OTEL_EXPORT_REDACT_ENABLED=true`）

---

## 7. 常见问题（Troubleshooting）

### 7.1 启动时 Ollama 没起来

AdamI 在 boot 时可能尝试 auto-start（`boot_manager.py`）：

- Linux：`systemctl start ollama`
- macOS：`ollama serve`

如果你不希望 AdamI 管理 Ollama 生命周期，请在环境中禁用（如果你有该开关）或确保 Ollama 先于 AdamI 启动。

### 7.2 本地模型响应慢/超时

调整：

- `ADAMI_ROUTER_OLLAMA_TIMEOUT_SEC`（默认 120s）
- 模型大小与硬件（CPU/RAM/磁盘）
- Ollama `num_ctx` / `num_predict`（在 `router.py` payload `options` 中）

### 7.3 macOS 上 MLX 加载失败

常见原因：

- 模型路径不可达/首次拉取耗时
- 内存不足

可先仅用 Ollama 验证链路，再打开 MLX。


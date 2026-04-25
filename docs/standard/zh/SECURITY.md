# AdamI — 安全与信任边界

**读者**：安全审计、合规审查、并购尽调团队。

本文映射开源树中**已实现**的控制措施；**不是**渗透测试报告。

---

## 1. 威胁模型（范围）

**范围内**

- **运动中的密钥**：用户文本、工具载荷、日志。
- **不可信代码路径**：下载或 LLM 生成的「技能」。
- **执行隔离**：可选的 Docker 沙箱。

**范围外**（须在外层叠加）

- 云 IAM、VPC 边界、KMS 策略等。

---

## 2. 总线中间件 — 敏感信息脱敏

**组件**：`adami_kernel.guardian.sensitive_filter.SensitiveFilter`

- 在 `EventBus.initialize()` 中注册为中间件。
- 正则族覆盖类 API Key、密码、电话、邮箱、卡号模式及通用 `secret|token|auth|key` 赋值。
- 对 `event.payload` 字典/列表 **递归** 脱敏并防循环引用。
- 部分键（`chat_id`、`discord_channel_id` 等）白名单以免破坏路由。

**局限**：正则纵深防御不完美 —— 须配合 **最小权限密钥** 与外部 DLP（监管数据场景）。

---

## 3. AST 审计 — 插件与外源代码

**组件**：`adami_kernel.orchestrator.loader.PluginLoader.audit_code`

- 将 Python 解析为 AST 并遍历节点。
- 拦截禁止 import（`os`、`sys`、`subprocess`…）、危险内置（`eval`、`exec`、`open`…）、高风险属性/调用形态，及匹配已知敌对模式的字符串常量。
- 返回 **`bool`**：`False` 表示拒绝加载。

**下游**：`SkillInspector`、`ClawHub.download_and_audit` 在接纳外源「基因」前调用此门闩。

---

## 4. 技能洗髓 — 对生成代码的 AST 变换

**组件**：`adami_kernel.skill_manager.skill_washer.SkillWasher`

- 使用 `ast.NodeTransformer` 将命中 **危险关键字表** 的调用（如 `os.system`、`subprocess`、`eval(`）替换为抛错桩代码。
- AST 解析失败时回退字符串清洗，并可返回 **最小安全模板**。

定位为审计之后的 **第二道防线**，面向 LLM 产出代码。

---

## 5. 密钥保险库（本地签名材料）

**组件**：`adami_kernel.guardian.tls.LocalSecretVault`

- 持久化 JSON keystore（`settings.path_keystore_json`），生成 `master_node`（`secrets.token_hex(32)`）。
- 类 Unix 上对 keystore 文件尝试 `chmod 0o600`。
- 提供基于 **HMAC-SHA256** 的 `generate_token` / `verify_token`。

**运维建议**：将 keystore 视为机器级机密；备份仅经安全信道。

---

## 6. 梦境沙箱（可选代码执行）

**组件**：`adami_kernel.cortex.dream_sandbox.DreamSandbox`

- 在 Docker 可用时使用；设计意图包括 **bridge 网络** 与容器内 **Dummy API Key**，降低沙箱误连真实供应商的风险。
- Docker 不可用时行为降级并有日志 —— **不得**假设仍存在隔离。

---

## 7. RBAC 与 DLQ 挂钩

`EventBus` 可选接入 `rbac` 与 `dlq_db`：

- 发布失败 / 中间件拦截可能入 DLQ 供后续回放（见 `bus.py`）。

---

## 8. 协作式重启

`LifecycleManager.request_process_restart()` 标记关机后 `execv` 重启路径。**威胁考量**：能在部署中触发该能力的主体可造成 **可用性影响** —— 须保护 Telegram/Discord Token 与管理面。

---

## 9. 加固清单（部署侧）

1. 定期轮换大模型与通讯平台 Token；仅存放于 `.env`。
2. 以专用服务账户运行内核；若不需要宿主机 Docker 套接字则勿授予。
3. 启用集中日志与保留策略；附件侧策略脱敏。
4. CI 中执行 `ruff`、`pyright`、`pytest`（见 [CONTRIBUTING.md](CONTRIBUTING.md)）。

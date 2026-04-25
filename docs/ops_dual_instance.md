# 双实例运维约定（阶段 6）

与任务短纲一致：**实例 A 负责采集**，**实例 B 负责定时训练并产出策略 manifest**；**两台实例共用同一策略目录语义**（通过 NFS、对象存储挂载、或 rsync 等方式实现，三选一即可）。

## 角色

| 实例 | 典型位置 | 职责 | 建议配置 |
|------|----------|------|----------|
| **A** | Mac / 边缘 | 只跑内核与用户交互；**开启经验采集**，不写训练 manifest | `ADAMI_EXPERIENCE_ENABLED=true`；`ADAMI_EXPERIENCE_DIR` 指向可同步路径 |
| **B** | 阿里云 ECS 等 | **定时**执行 `adami-train-agl`（或等价训练入口），读经验目录、写 `manifest.json` 与模板 | 与训练 CLI 文档一致；输出目录与 `ADAMI_POLICY_DIR` 对齐或 rsync 到共享策略路径 |

两台均需能读到**同一份策略树**（至少包含 `ADAMI_POLICY_MANIFEST_FILENAME`，默认 `manifest.json`，及 manifest 中引用的模板路径）。内核侧通过 `ADAMI_POLICY_RELOAD_INTERVAL_SEC`（默认 60s）轮询热更新。

## 策略目录的三种落地方式（选一）

1. **NFS**：A、B 挂载同一服务端路径，`ADAMI_POLICY_DIR` 均指向该挂载点。训练写 manifest 后，A 在下一轮 reload 内自动拾取。
2. **OSS / 对象存储 FUSE**：将 bucket 挂载到两机相同挂载点，配置同上。注意 FUSE 延迟与一致性，可适当调大轮询间隔。
3. **双向 rsync**：无共享盘时，用 `scripts/sync_experience.sh` 等脚本在 A↔B 间同步**仅** `experience/` 与 `policy/`（见下文）。常见模式：A `push-experience`，B 训练后 A `pull-policy`；或由 cron 在 B 上 `pull-experience`、`push-policy`。

**不要**默认同步整盘 `.adami_data`（含本地模型缓存、sqlite、其他状态），除非你有明确备份需求；示例脚本只同步与经验池、策略相关的两个目录。

## 环境变量（与 `config.py` 对齐）

- `ADAMI_EXPERIENCE_DIR`：经验落盘根目录（默认 `.adami_data/experience`）。
- `ADAMI_POLICY_DIR`：策略包根目录（默认 `.adami_data/policy`）。
- `ADAMI_POLICY_RELOAD_INTERVAL_SEC`：热更新轮询间隔。
- 训练产出目录：见 `ADAMI_AGL_TRAIN_OUTPUT_DIR`；可与 `ADAMI_POLICY_DIR` 相同，或训练写到临时目录再 rsync 到共享 `policy/`。

## 示例脚本：`scripts/sync_experience.sh`

Mac ↔ 阿里云仅同步经验与策略两个子目录（`rsync` + `ssh`）。

1. 在远端创建父目录（示例）：
   - `ADAMI_SYNC_REMOTE_BASE=/home/ubuntu/adami_data`
   - 其下使用 `experience/` 与 `policy/` 与本地目录名一致。

2. 本机设置并执行（示例）：

```bash
chmod +x scripts/sync_experience.sh
export ADAMI_SYNC_REMOTE="ubuntu@your-ecs.aliyuncs.com"
export ADAMI_SYNC_REMOTE_BASE="/home/ubuntu/adami_data"
# 可选：与 .env 一致
export ADAMI_EXPERIENCE_DIR="$PWD/.adami_data/experience"
export ADAMI_POLICY_DIR="$PWD/.adami_data/policy"

# 采集机 A：把经验推到云端供 B 训练
./scripts/sync_experience.sh push-experience

# 采集机 A：训练完成后拉回策略
./scripts/sync_experience.sh pull-policy
```

3. 训练机 B：拉经验、推策略（示例）：

```bash
./scripts/sync_experience.sh pull-experience
# ... 运行 adami-train-agl ...
./scripts/sync_experience.sh push-policy
```

4. 可选：`RSYNC_DELETE=1` 会在 rsync 时加 `--delete`（策略目录若需严格镜像可开；经验目录一般保持默认 **不** delete，避免误删历史 jsonl）。

5. 自定义 SSH：`export ADAMI_SSH='ssh -i ~/.ssh/your_key -o StrictHostKeyChecking=accept-new'`

6. 演练：`./scripts/sync_experience.sh push-experience --dry-run`

## 与短纲的对应关系

- **A 只采集**：不在 A 上跑训练 CLI；经验进入 `ADAMI_EXPERIENCE_DIR`。
- **B 定时训练**：cron/systemd timer 调用 `adami-train-agl`，产出 manifest 至共享或可被 A 拉取的 `ADAMI_POLICY_DIR`。
- **两台轮询同一策略目录**：通过 NFS / OSS FUSE / rsync 保证 `ADAMI_POLICY_DIR` 内容最终一致即可；内核只依赖目录与轮询，不绑定具体同步产品。

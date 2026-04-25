#!/usr/bin/env bash
# 阶段 6 示例：仅同步经验池与策略目录（与 ADAMI_EXPERIENCE_DIR / ADAMI_POLICY_DIR 对齐），
# 不包含整盘 .adami_data（无 episodic、sqlite、缓存等）。
#
# 依赖：本机与远端已安装 openssh + rsync；已配置 SSH 密钥或 agent。
#
# 用法：
#   export ADAMI_SYNC_REMOTE="ubuntu@your-ecs.aliyuncs.com"
#   export ADAMI_SYNC_REMOTE_BASE="/home/ubuntu/adami_data"   # 远端 experience/ 与 policy/ 的父目录
#   ./scripts/sync_experience.sh push-experience
#   ./scripts/sync_experience.sh pull-policy
#
# 可选环境变量：
#   ADAMI_EXPERIENCE_DIR   默认 $PWD/.adami_data/experience
#   ADAMI_POLICY_DIR       默认 $PWD/.adami_data/policy
#   ADAMI_SSH              默认 "ssh"，可改为 "ssh -i ~/.ssh/id_ed25519_aliyun"
#   RSYNC_DELETE           设为 1 时对目标侧使用 --delete（策略目录慎用；经验目录一般不建议）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ACTION="${1:-}"
if [[ -z "$ACTION" ]]; then
  echo "用法: $0 <push-experience|pull-experience|push-policy|pull-policy|push-both|pull-both> [--dry-run]" >&2
  exit 1
fi

DRY_RUN=0
if [[ "${2:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

REMOTE="${ADAMI_SYNC_REMOTE:-}"
if [[ -z "$REMOTE" ]]; then
  echo "请设置 ADAMI_SYNC_REMOTE，例如: export ADAMI_SYNC_REMOTE='user@ecs.example.com'" >&2
  exit 1
fi

REMOTE_BASE="${ADAMI_SYNC_REMOTE_BASE:-}"
if [[ -z "$REMOTE_BASE" ]]; then
  echo "请设置 ADAMI_SYNC_REMOTE_BASE，例如远端 experience 与 policy 的父目录: /home/ubuntu/adami_data" >&2
  exit 1
fi

LOCAL_XP="${ADAMI_EXPERIENCE_DIR:-$ROOT/.adami_data/experience}"
LOCAL_PO="${ADAMI_POLICY_DIR:-$ROOT/.adami_data/policy}"
REMOTE_XP="${REMOTE_BASE%/}/experience"
REMOTE_PO="${REMOTE_BASE%/}/policy"

# 整串传给 rsync -e，例如: ssh 或 ssh -i ~/.ssh/aliyun -o IdentitiesOnly=yes
RSH="${ADAMI_SSH:-ssh}"

RSYNC_BASE=(rsync -avz -e "$RSH")
if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC_BASE+=(--dry-run)
fi

if [[ "${RSYNC_DELETE:-0}" == "1" ]]; then
  RSYNC_BASE+=(--delete)
fi

run_rsync() {
  local src="$1"
  local dst="$2"
  mkdir -p "$LOCAL_XP" "$LOCAL_PO" 2>/dev/null || true
  "${RSYNC_BASE[@]}" "$src" "$dst"
}

case "$ACTION" in
  push-experience)
    run_rsync "${LOCAL_XP}/" "${REMOTE}:${REMOTE_XP}/"
    ;;
  pull-experience)
    run_rsync "${REMOTE}:${REMOTE_XP}/" "${LOCAL_XP}/"
    ;;
  push-policy)
    run_rsync "${LOCAL_PO}/" "${REMOTE}:${REMOTE_PO}/"
    ;;
  pull-policy)
    run_rsync "${REMOTE}:${REMOTE_PO}/" "${LOCAL_PO}/"
    ;;
  push-both)
    run_rsync "${LOCAL_XP}/" "${REMOTE}:${REMOTE_XP}/"
    run_rsync "${LOCAL_PO}/" "${REMOTE}:${REMOTE_PO}/"
    ;;
  pull-both)
    run_rsync "${REMOTE}:${REMOTE_XP}/" "${LOCAL_XP}/"
    run_rsync "${REMOTE}:${REMOTE_PO}/" "${LOCAL_PO}/"
    ;;
  *)
    echo "未知动作: $ACTION" >&2
    exit 1
    ;;
esac

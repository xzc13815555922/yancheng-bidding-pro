#!/bin/bash
# run-morning.sh — 每天 8:00 跑一次 (采通 + PDF + 推群 一气呵成)
#
# 2026-07-23 老板明确: 8:00 这一轮必须先采完富化完再出 PDF,
# 不能并行 (避免老数据 vs 新数据的 PDF 内容不一致).
#
# 流程 (串行):
#   1. incremental_collect.py --mode fast (采通, 含群通报)
#   2. generate_*.py x 4 (出 4 份 PDF, 用刚采完的 unified.db)
#   3. push-pdfs.sh (推群, v3.0 焊死版)
#
# 撞车保护:
#   - flock -n 锁 /tmp/openclaw/ybp-collect.lock (防与 9-20 点 collect 并发)
#   - 单实例超时 25 分钟 (SIGTERM), 超时 kill
#   - 失败不回滚 (采通跑过就标记 done, PDF 缺再单独补推)

set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/usr/bin/python3"
LOCK_FILE="/tmp/openclaw/ybp-collect.lock"
LOG_FILE="/tmp/openclaw/morning-$(date +%Y%m%d_%H%M%S).log"

# —— 临时锁 —— 多 cron 互斥
exec 9>"$LOCK_FILE"
if ! /usr/bin/flock -n 9; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ 另一个采通仍在跑, run-morning 退出 (由下次 cron 接手)"
    exit 0
fi

exec > >(tee -a "$LOG_FILE") 2>&1
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "====== run-morning.sh 开始 (8:00 一气呵成) ======"

# —— 总超时 25 分钟 ——
SCRIPT_PID=$$
cleanup_timeout() {
    log "⚠️ run-morning 到达 25 分钟超时, SIGTERM 子进程"
    pkill -P "$SCRIPT_PID" 2>/dev/null || true
    exit 124
}
trap cleanup_timeout SIGALRM
( sleep 1500; kill -ALRM "$SCRIPT_PID" ) &
TIMER_PID=$!

# ─── Step 1: 采通 + 群通报 ───
log "[Step 1] incremental_collect.py --mode fast"
cd "$PROJ_DIR"
$PYTHON incremental_collect.py --mode fast
log "[Step 1] 采通完成"

# ─── Step 2: 4 份 PDF (用刚采完的 unified.db) ───
MONTH="$(date +%Y-%m)"
DATE="$(date +%Y-%m-%d)"

log "[Step 2.1] generate_tender_report.py"
$PYTHON generate_tender_report.py "$MONTH" || log "⚠️ generate_tender_report 失败 (PDF 1 缺失)"

log "[Step 2.2] generate_countdown_report_pdf.py"
$PYTHON generate_countdown_report_pdf.py "$DATE" || log "⚠️ generate_countdown_report_pdf 失败 (PDF 2 缺失)"

log "[Step 2.3] generate_operator_combined_report.py"
$PYTHON generate_operator_combined_report.py --month "$MONTH" || log "⚠️ generate_operator_combined_report 失败 (PDF 3 缺失)"

log "[Step 2.4] generate_intention_report.py"
$PYTHON generate_intention_report.py "$MONTH" || log "⚠️ generate_intention_report 失败 (PDF 4 缺失)"

# ─── Step 3: 推群 (焊死 push-pdfs.sh v3.0) ───
log "[Step 3] push-pdfs.sh 推群"
if /bin/bash /Users/yc/.openclaw/agents/executor/scripts/push-pdfs.sh; then
    log "✅ push-pdfs.sh 成功"
else
    PUSH_RC=$?
    log "❌ push-pdfs.sh 失败 rc=$PUSH_RC (PDF 仍在磁盘, 下次 cron 自动补推)"
    # 写 CRITICAL 飞书告警 (不丢日志)
    if command -v openclaw >/dev/null 2>&1; then
        openclaw message send \
            --channel feishu \
            --account executor \
            --target "open_id:ou_09c0f6a80ee31cd768628371292a145b" \
            --message "🚨 CRITICAL: run-morning push-pdfs.sh 失败 rc=$PUSH_RC
日志: $LOG_FILE" >> "$LOG_FILE" 2>&1 || true
    fi
fi

# 关掉超时
kill "$TIMER_PID" 2>/dev/null || true

log "====== run-morning.sh 完成 ======"
log "日志: $LOG_FILE"

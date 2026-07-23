#!/bin/bash
# run-daily-report.sh — 每日 PDF 日报 + 推送 (8:30 cron 调用, 替代旧 5:00 大流程+8:35推)
#
# 背景 (2026-07-23):
#   原 5:00 大流程 (cd8c4dbf) 取消, 改用 10 分钟 incremental_collect.py 增量采集.
#   5:00 不再跑 PDF 生成 → 改到 8:30 跑, 然后直推飞书群.
#   push-pdfs.sh 仍然负责推群 (被本脚本串起来).
#
# 流程:
#   verify_quality (前置校验) → 4 份 PDF 生成 → push-pdfs.sh 推群
#
# 注意:
#   - verify_quality FAIL: 不阻断 PDF 生成 (已记 CRITICAL), 但 skip push 不推群
#     防止失格数据直接发到客户面前
#   - PDF 生成失败: 飞书 CRITICAL 告警 CEO
#   - push-pdfs.sh 焊死版, hash 自校验, 不需要 agent 改

set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/usr/bin/python3"
cd "$PROJ_DIR"

LOG_FILE="/tmp/openclaw/daily-report-$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

MONTH="$(date +%Y-%m)"
DATE="$(date +%Y-%m-%d)"

log "====== run-daily-report.sh 开始 ======"
log "月份: $MONTH 日期: $DATE"

# ────────────────────────────────────────
# Step A: 前置 verify_quality (不阻断, 仅标记)
# ────────────────────────────────────────
log "[Step A] verify_quality.py (前置校验, 不阻断)"
set +e
$PYTHON verify_quality.py
VERIFY_RC=$?
set -e
if [ "$VERIFY_RC" -ne 0 ]; then
    log "⚠️ verify_quality FAIL rc=$VERIFY_RC (已记 CRITICAL, 继续生成 PDF)"
    # 写 CRITICAL 文件 (不飞书推, 沿用 run-full-pipeline.sh 的抑制逻辑)
    TS="$(date +%Y%m%d_%H%M%S)"
    CRIT_FILE="/tmp/openclaw/CRITICAL_daily_report_quality_${TS}.md"
    {
        echo "# CRITICAL: daily-report verify_quality FAIL"
        echo
        echo "- 时间: $(date -Iseconds)"
        echo "- verify_quality 退出码: $VERIFY_RC"
        echo "- 决策: 不阻断 PDF 生成 (质量门 FAIL 已知, PDF 仍出)"
        echo "- 日志: $LOG_FILE"
    } > "$CRIT_FILE"
    log "📝 CRITICAL(quality) 已写: $CRIT_FILE"
fi

# ────────────────────────────────────────
# Step B: 4 份 PDF 生成
# ────────────────────────────────────────
log "[Step B] generate_tender_report.py"
$PYTHON generate_tender_report.py "$MONTH" || {
    log "❌ generate_tender_report 失败 (PDF 1 缺失)"
}

log "[Step B] generate_countdown_report_pdf.py"
$PYTHON generate_countdown_report_pdf.py "$DATE" || {
    log "❌ generate_countdown_report_pdf 失败 (PDF 2 缺失)"
}

log "[Step B] generate_operator_combined_report.py"
$PYTHON generate_operator_combined_report.py --month "$MONTH" || {
    log "❌ generate_operator_combined_report 失败 (PDF 3 缺失)"
}

log "[Step B] generate_intention_report.py"
$PYTHON generate_intention_report.py "$MONTH" || {
    log "❌ generate_intention_report 失败 (PDF 4 缺失)"
}

# ────────────────────────────────────────
# Step C: 检查 4 个 PDF 都生成, 推群
# ────────────────────────────────────────
EXPECTED_PDFS=(
    "output/盐开招标公告_${MONTH//-/}.pdf"
    "output/盐开开标倒计时报告_${DATE//-/}.pdf"
    "output/盐城通信运营商中标报告_${MONTH}.pdf"
    "output/盐开采购意向报告_${MONTH//-/}.pdf"
)

MISSING=()
for p in "${EXPECTED_PDFS[@]}"; do
    if [ ! -f "$PROJ_DIR/$p" ]; then
        MISSING+=("$p")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    log "❌ 缺失 ${#MISSING[@]} 份 PDF: ${MISSING[*]}"
    log "⚠️ 不推群 (飞书 CRITICAL 告警 CEO)"
    # 推个人飞书 (CEO)
    if command -v openclaw >/dev/null 2>&1; then
        openclaw message send \
            --channel feishu \
            --account executor \
            --target "open_id:ou_09c0f6a80ee31cd768628371292a145b" \
            --message "🚨 CRITICAL: run-daily-report PDF 缺失
缺失: ${MISSING[*]}
日志: $LOG_FILE
月: $MONTH 日: $DATE" >> "$LOG_FILE" 2>&1 || true
    fi
    exit 1
fi

# ────────────────────────────────────────
# Step D: 推群 (v3.0 焊死 push-pdfs.sh + hash 自校验)
# ────────────────────────────────────────
log "[Step D] push-pdfs.sh (推 4 份 PDF 到飞书群)"
/bin/bash /Users/yc/.openclaw/agents/executor/scripts/push-pdfs.sh 2>&1 || {
    log "❌ push-pdfs.sh 失败 rc=$?"
    exit 2
}

log "✅ 日报流程完成"
log "日志: $LOG_FILE"
log "====== 结束 ======"

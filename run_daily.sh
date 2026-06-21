#!/bin/bash
# 每日凌晨2点全流程：采集 → 富化 → 打标
set -e

WORKSPACE="$HOME/.openclaw/workspace/yancheng-bidding-pro"
LOG="/tmp/openclaw/daily-$(date +%Y%m%d).log"
mkdir -p /tmp/openclaw

log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"; }

cd "$WORKSPACE"
log "=== 每日采集任务开始 $(date '+%Y-%m-%d') ==="

log "1/6 增量采集（含PDF→MD转换）..."
python3 run_collection.py --days 3 >> "$LOG" 2>&1

log "2/6 补全详情..."
python3 enrich_details.py >> "$LOG" 2>&1

log "3/6 标准区县分类..."
python3 add_std_district.py >> "$LOG" 2>&1

log "4/6 标准项目分类..."
python3 add_std_category.py >> "$LOG" 2>&1

log "5/6 构建统一数据库..."
python3 build_unified.py >> "$LOG" 2>&1

log "6/6 数据质量验证..."
python3 verify_quality.py >> "$LOG" 2>&1 || {
    log "⚠️  质量验证未通过，详见日志 $LOG"
    # 不以非零退出，避免阻断通知发送
}

log "=== 任务完成 ==="

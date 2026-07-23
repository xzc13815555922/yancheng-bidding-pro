#!/bin/bash
# run-tyc.sh — 每天 7 点跑 tyc 天眼查采集 (cron ybp-tyc-daily 调用)
#
# 流程:
#   1. tyc_crawler.py --days 1 (采昨日+今日, 一页不足退出)
#   2. RC != 0 → Cookie 可能过期: 写 CRITICAL 告警 CEO (不阻断下游)
#   3. RC == 0 → 写日志 + 数 total
#
# 注意:
#   - 不调用 verify_quality (tyc 不纳入 ybp 基线)
#   - Cookie 过期是 tyc_crawler 的已知机制, 每 30 天手重登一次

set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/usr/bin/python3"
cd "$PROJ_DIR"

LOG_FILE="/tmp/openclaw/tyc-daily-$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "====== run-tyc.sh 开始 ======"

TS="$(date +%Y%m%d_%H%M%S)"
COOKIE="/Users/yc/.openclaw/workspace/yancheng-bidding-pro/data/cookies.json"

log "[1/2] cookie 存在性检查"
if [ ! -f "$COOKIE" ]; then
    log "⚠️ cookies.json 不存在"
fi

log "[2/2] tyc_crawler.py --days 1"
set +e
$PYTHON crawlers/tyc_crawler.py --days 1
TYC_RC=$?
set -e

if [ "$TYC_RC" -ne 0 ]; then
    log "❌ tyc_crawler 失败 rc=$TYC_RC"
    CRIT_FILE="/tmp/openclaw/CRITICAL_tyc_${TS}.md"
    {
        echo "# CRITICAL: tyc 天眼查采集失败"
        echo
        echo "- 时间: $(date -Iseconds)"
        echo "- 退出码: $TYC_RC"
        echo "- 排查: 1) cookies.json 是否过期 (上站检查); 2) 手动 python3 crawlers/tyc_login.py 重登"
        echo "- 日志: $LOG_FILE"
    } > "$CRIT_FILE"
    log "📝 CRITICAL(tyc) 已写: $CRIT_FILE"
    log "⚠️ 不影响其他 cron, 推个人飞书告警"
    if command -v openclaw >/dev/null 2>&1; then
        openclaw message send \
            --channel feishu \
            --account executor \
            --target "open_id:ou_09c0f6a80ee31cd768628371292a145b" \
            --message "🚨 CRITICAL: tyc 天眼查采集失败 rc=$TYC_RC
CRIT: $CRIT_FILE
可能是 cookies.json 过期, 下次手动跑: python3 crawlers/tyc_login.py" >> "$LOG_FILE" 2>&1 || true
    fi
    exit 0  # 不阻断
fi

# RC == 0: 数一下今日新增
$PYTHON -c "
import sqlite3
c = sqlite3.connect('data/tyc.db')
cur = c.cursor()
cur.execute('SELECT COUNT(*) FROM bids')
print(f'  tyc.db 总条数: {cur.fetchone()[0]}')
" || true

log "✅ tyc 采集完成"
log "====== 结束 ======"

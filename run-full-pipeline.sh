#!/bin/bash
# run-full-pipeline.sh — yancheng-bidding-pro 全流程采集脚本
# 每天 05:00 cron 执行
# 流程：12站采集 → 天眼查采集 → 富化 → 打标 → 统一库 → 质量验证 → 3份报告 → Excel导出
#
# 用法: bash run-full-pipeline.sh [--days N] [--skip-tyc]
#   --days N      采集近N天数据（默认3）
#   --skip-tyc    跳过天眼查采集（调试用）
#   --month M     报告月份，如 2026-06（默认当月）

set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/usr/bin/python3"
DAYS="${2:-3}"
MONTH="${4:-$(date +%Y-%m)}"
LOG_FILE="/tmp/openclaw/ybp-pipeline-$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "====== yancheng-bidding-pro 全流程开始 ======"
log "工作目录: $PROJ_DIR"
log "采集天数: $DAYS"
log "报告月份: $MONTH"
log "日志文件: $LOG_FILE"

cd "$PROJ_DIR"

# ============================================
# 第1步：增量采集（近3天，12站）
# ============================================
log "[Step 1/10] run_collection.py --days $DAYS"
$PYTHON run_collection.py --days "$DAYS" || {
    log "⚠️  run_collection 返回非0，继续后续步骤"
}

# ============================================
# 第2步：天眼查运营商中标采集（仅取近1天，去重已采数据）
# ============================================
if [ "${SKIP_TYC:-}" != "1" ]; then
    log "[Step 2/10] tyc_crawler.py --days 1 (天眼查运营商中标采集)"
    $PYTHON crawlers/tyc_crawler.py --days 1 || {
        log "⚠️  tyc_crawler 失败（可能 Cookie 过期），继续后续步骤"
    }
else
    log "[Step 2/10] 跳过天眼查采集 (SKIP_TYC=1)"
fi

# ============================================
# 第2.5步：补抓新采记录的 HTML 详情页（保证 page_path 填充）
# 2026-06-25 审计 P0-1 修复：在 Step 2 和 Step 3 之间插入
# 原因：原 pipeline 缺 download_site_pages，新采的 HTML 站记录
#       detail_url 有了但 page_path 永远是 None，导致 Step 3
#       enrich_details 走 HTTP fallback 抓取，浪费带宽、易被反爬
# ============================================
log "[Step 2.5/10] download_site_pages.py (补抓 HTML 详情页 → MD)"
$PYTHON download_site_pages.py || {
    log "⚠️  download_site_pages 失败，继续后续步骤"
}

# ============================================
# 第3步：详情页富化补全
# ============================================
log "[Step 3/10] enrich_details.py"
$PYTHON enrich_details.py || {
    log "⚠️  enrich_details 返回非0，继续"
}

# ============================================
# 第3.5步：提取中小微企业标签 (P1-2026-07-06)
# 从已抓的 MD 缓存提取 sme_target, 写 unified.db
# ============================================
log "[Step 3.5/10] extract_sme_target.py (中小微企业标签提取)"
$PYTHON extract_sme_target.py || {
    log "⚠️  extract_sme_target 返回非0，继续"
}

# ============================================
# 第4步：区县标准化打标
# ============================================
log "[Step 4/10] add_std_district.py"
$PYTHON add_std_district.py || {
    log "⚠️  add_std_district 返回非0，继续"
}

# ============================================
# 第5步：类别打标
# ============================================
log "[Step 5/10] add_std_category.py"
$PYTHON add_std_category.py || {
    log "⚠️  add_std_category 返回非0，继续"
}

# ============================================
# 第6步：生成 unified.db（三张表）
# ============================================
log "[Step 6/10] build_unified.py"
$PYTHON build_unified.py || {
    log "⚠️  build_unified 返回非0，继续"
}

# ============================================
# 第7步：数据质量验证
# ============================================
log "[Step 7/10] verify_quality.py"
$PYTHON verify_quality.py || {
    log "⚠️  verify_quality 返回非0，继续"
}

# ============================================
# 第8步：生成报告① — 盐开招标公告月报 PDF
# ============================================
log "[Step 8/10] generate_tender_report.py (月报)"
$PYTHON generate_tender_report.py || {
    log "⚠️  generate_tender_report 失败"
}

# ============================================
# 第9步：生成报告② — 盐开开标倒计时报告 PDF
# ============================================
log "[Step 9/10] generate_countdown_report_pdf.py (倒计时)"
$PYTHON generate_countdown_report_pdf.py || {
    log "⚠️  generate_countdown_report_pdf 失败"
}

# ============================================
# 第10步：生成报告③ — 运营商综合月报 PDF
# ============================================
log "[Step 10/10] generate_operator_combined_report.py (运营商综合月报)"
$PYTHON generate_operator_combined_report.py --month "$MONTH" || {
    log "⚠️  generate_operator_combined_report 失败"
}

# ============================================
# 第11步：生成报告④ — 盐开采购意向报告 PDF
# ============================================
log "[Step 11/11] generate_intention_report.py (盐开采购意向报告)"
$PYTHON generate_intention_report.py "$MONTH" || {
    log "⚠️  generate_intention_report 失败"
}

# ============================================
# 汇总
# ============================================
log ""
log "====== 全流程完成 ======"

# 统计 unified.db 条数
$PYTHON -c "
import sqlite3, os
path = os.path.join('$PROJ_DIR', 'data', 'unified.db')
if os.path.exists(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    for t in ['tender', 'award', 'intention', 'other']:
        cur.execute(f'SELECT COUNT(*) FROM {t}')
        print(f'unified.{t}: {cur.fetchone()[0]}条')
    conn.close()
"

# 列出本次生成的 4 个 PDF
echo ""
echo "--- 生成的文件 ---"
ls -lh output/盐开招标公告_$(date +%Y%m).pdf 2>/dev/null && echo "  ✔ 月报PDF"
ls -lh output/盐开开标倒计时报告_$(date +%Y%m%d).pdf 2>/dev/null && echo "  ✔ 倒计时PDF"
ls -lh output/盐城通信运营商中标报告_$(date +%Y-%m).pdf 2>/dev/null && echo "  ✔ 运营商月报PDF"
ls -lh output/盐开采购意向报告_$(date +%Y%m).pdf 2>/dev/null && echo "  ✔ 采购意向PDF"

log "日志: $LOG_FILE"
log "====== 结束 ======"

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
# 第0.5步：初始化数据治理表（幂等，2026-07-18 小标数据治理接接接接接）
# ──────────────────────────────────
# 目标：确保 unified.db 有 unified_audit 表，13 站 db 有 failed_records 表
# 幂等：CREATE IF NOT EXISTS，多次跑安全
# 风险：0（仅创建表，不动现有数据）
# 验证：本地 3x重复跑均 EXIT:0，原数据 15146 条不变
# ============================================
log "[Step 0.5/11] init_unified_audit.py (建统一审计表)"
$PYTHON scripts/utils/init_unified_audit.py >> "$LOG_FILE" 2>&1 || {
    log "⚠️  init_unified_audit 失败（不影响采集流）"
}
log "[Step 0.5/11] init_failed_records.py (建失败隔离表 × 13站)"
$PYTHON scripts/utils/init_failed_records.py >> "$LOG_FILE" 2>&1 || {
    log "⚠️  init_failed_records 失败（不影响采集流）"
}

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
# 第2.6步：批次意向展开 (2026-07-12 补, CEO 拍板方案 A)
# 把 yancheng_gov 详情页 .md 的"批次公告表格"解析为 expected_list JSON
# 写入 yancheng_gov.db.notices.expected_list
# build_unified.py 在 Step 6 用 expected_list[0].name 替换批次标题
# 缺这一步 → 7/6 起所有新批次 PDF 都显示"xx批.政府采购"批次名
# ============================================
log "[Step 2.6/10] expand_intention.py (批次意向展开 → expected_list JSON)"
$PYTHON scripts/utils/expand_intention.py || {
    log "⚠️  expand_intention 失败，继续后续步骤"
}

# ============================================
# 第3步：详情页富化补全
# ============================================
log "[Step 3/10] enrich_details.py"
$PYTHON enrich_details.py || {
    log "⚠️  enrich_details 返回非0，继续"
}

# ============================================
# 第3.5步：提取中小微企业标签 (P1-2026-07-06, CEO 拍板)
# 从已抓的 MD 缓存提取 sme_target, 写 unified.db
# 用于报表清单加列「中小微」 (专门=绿/优惠=橙)
# ============================================
log "[Step 3.5/10] extract_sme_target.py (中小微企业标签提取 → 写 unified.db)"
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
# 第6.5步：重新提取 SME 标签 (P2-3 2026-07-07)
# build_unified DROP+重建会清掉 sme_target 列提取的数据, 必须 build 后再跑一次
# ============================================
log "[Step 6.5/10] extract_sme_target.py (P2-3 修复: build_unified 后再跑一次)"
$PYTHON extract_sme_target.py || {
    log "⚠️  extract_sme_target 二次跑失败, SME 列可能为空"
}

# ============================================
# 第7步：数据质量验证（P0 修复 2026-07-18 小标审计）
# ──────────────────────────────────
# 原行为：FAIL 时仅 warning + 继续（导致 8 项基线 FAIL 不被暴露）
# 新行为：FAIL 时记 CRITICAL + 飞书告警 CEO + exit 1（让 8 项回归可见）
# 原因：审计证据 — ypb/verify_quality.py 跑出 8 项 FAIL 但 pipeline 不 halt
# ============================================
log "[Step 7/10] verify_quality.py"
set +e
$PYTHON verify_quality.py
VERIFY_RC=$?
set -e
if [ "$VERIFY_RC" -ne 0 ]; then
    # 抽取 FAIL 摘要（先存变量，避免在 --message 中命令替换碰括号）
    FAIL_SUMMARY="$(grep -E 'FAIL|❌' /tmp/openclaw/ybp-pipeline-*.log 2>/dev/null | tail -15 || true)"
    [ -z "$FAIL_SUMMARY" ] && FAIL_SUMMARY="（无 FAIL 行）"
    # 写 CRITICAL 文件
    TS="$(date +%Y%m%d_%H%M%S)"
    CRIT_QUALITY="/tmp/openclaw/CRITICAL_verify_quality_${TS}.md"
    {
        echo "# CRITICAL: ybp 数据质量基线不达标"
        echo
        echo "- 时间: $(date -Iseconds)"
        echo "- 步骤: run-full-pipeline.sh Step 7 (verify_quality.py)"
        echo "- 退出码: $VERIFY_RC"
        echo "- 详情: 见当日 ybp-pipeline 日志"
        echo "- 影响: 今日采集数据 quality 不达标，需排查后再触发"
        echo
        echo "## 排查路径"
        echo "1. grep FAIL /tmp/openclaw/ybp-pipeline-*.log"
        echo "2. cd ~/.openclaw/workspace/yancheng-bidding-pro && python3 verify_quality.py"
        echo "3. 对比 config.py SITE_BASELINES 与现场不符项"
    } > "$CRIT_QUALITY"
    log "📝 CRITICAL(verify_quality) 已写: $CRIT_QUALITY"
    log "📋 FAIL 摘要:"
    echo "$FAIL_SUMMARY" | while read -r line; do log "    $line"; done
    # 飞书告警（消息文本先放到变量，避免引号嵌套崩 bash）
    ALERT_MSG="🚨 CRITICAL: ybp 数据质量基线不达标（verify_quality 退出码 ${VERIFY_RC}）
ypb 全流程已暂停，避免把失格数据传给下游报表。
详情：CRIT_QUALITY=${CRIT_QUALITY}
当日失败摘要：
${FAIL_SUMMARY}
行动建议：检查基线失败站点 → 重跑采集 → 重跑 verify_quality。"
    openclaw message send \
        --channel feishu \
        --account executor \
        --target "open_id:ou_09c0f6a80ee31cd768628371292a145b" \
        --message "$ALERT_MSG" >> "$LOG_FILE" 2>&1 || log "⚠️ 质量告警推送失败（不影响 halt）"
    log "❌ 数据质量不达标，pipeline 退出码 $VERIFY_RC（暂停后续步骤）"
    exit "$VERIFY_RC"
fi

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
# 第11.5步：DB 自动备份（幂等，2026-07-18 小标数据治理接接接接接）
# ──────────────────────────────────
# 目标：报表生成后立即备份今日数据库，含 unified_audit/feedback 等治理表
# 幂等：今日备份已存在则跳过，仅清理过期备份
# 保留：默认 14 天（可调）
# 风险：低（sqlite3 backup API 是一致性快照）
# 验证：本地 14/14 备份成功，今日重跑跳过正确
# ============================================
log "[Step 11.5/11] backup_all_db.py (DB 全量备份 → 保留 14 天)"
$PYTHON scripts/utils/backup_all_db.py --keep 14 >> "$LOG_FILE" 2>&1 || {
    log "⚠️  backup_all_db 失败（不影响主流程）"
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

#!/usr/bin/env python3
"""
reenrich_yancheng_gov_p17.py — 2026-06-25 审计 P1-7 修复验证
=========================================================
清理 award 类 budget 误匹配:
1. 把 yancheng_gov.db 里 notice_type='award' 且 budget 不空的记录 budget 字段清空
2. 重新跑 parse_html_detail (新代码里 P1-7 排除词生效)
3. 统计修复前后 award 类 budget 填充数

默认 dry-run, 加 --confirm 才真清空 + 写回.

用法:
  python3 reenrich_yancheng_gov_p17.py            # dry-run
  python3 reenrich_yancheng_gov_p17.py --confirm  # 真清空 + 重 parse + 写回
"""
import argparse
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="真清空 + 写回")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent))
    from enrich_details import parse_html_detail

    db_path = DATA_DIR / "yancheng_gov.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 修复前: award 类 budget 不空的数
    pre_total = conn.execute("SELECT COUNT(*) FROM notices WHERE notice_type='award'").fetchone()[0]
    pre_budget = conn.execute("SELECT COUNT(*) FROM notices WHERE notice_type='award' AND budget IS NOT NULL AND budget>0").fetchone()[0]
    logger.info(f"[修复前] award 类: 总 {pre_total} 条, budget 不空 {pre_budget} 条 (误匹配嫌疑)")

    # 候选: award 类 + budget 不空 + page_path 存在
    rows = conn.execute("""
        SELECT id, page_path, budget
        FROM notices
        WHERE notice_type='award'
          AND budget IS NOT NULL AND budget > 0
          AND page_path IS NOT NULL AND page_path != ''
    """).fetchall()

    if not rows:
        logger.info("没有需要清理的 award 类 budget 记录")
        sys.exit(0)

    logger.info(f"候选清空 + 重 parse 记录: {len(rows)} 条")

    # 先 dry-run 看看新解析会不会有预算 (用 P1-7 排除词)
    will_reparse_with_budget = 0
    samples = []
    for r in rows[:5]:
        text = Path(r["page_path"]).read_text(encoding="utf-8", errors="replace")
        try:
            enriched = parse_html_detail(text, "award")
            new_budget = enriched.get("budget")
            samples.append((r["id"], r["budget"], new_budget))
            if new_budget:
                will_reparse_with_budget += 1
        except Exception as e:
            samples.append((r["id"], r["budget"], f"ERR: {e}"))

    logger.info(f"\n=== 样例 (前 5 条) ===")
    for rid, old, new in samples:
        logger.info(f"  {rid[:8]}  old_budget={old}  new_budget={new}")
    logger.info(f"\n前 5 条样例重 parse 出现 budget: {will_reparse_with_budget}/5")

    if not args.confirm:
        logger.info(f"\n[DRY-RUN] 加 --confirm 才真清空 + 写回 DB")
        sys.exit(0)

    # 真清空所有 award 类 budget
    conn.execute("BEGIN")
    n_cleared = conn.execute("""
        UPDATE notices SET budget=NULL, budget_unit=NULL, budget_text=NULL
        WHERE notice_type='award'
          AND budget IS NOT NULL AND budget > 0
    """).rowcount
    logger.info(f"\n=== 已清空 {n_cleared} 条 award 类 budget 字段 ===")

    # 重新 parse, 让 P1-7 排除词生效
    # 因为 parse_html_detail 会跳过已有 budget 字段 (默认逻辑),
    # 现在已清空, 重 parse 时会基于 P1-7 排除词判断
    # 简化: 只对 page_path 存在 + 仍需 parse 的做一遍
    rows2 = conn.execute("""
        SELECT id, page_path FROM notices
        WHERE notice_type='award'
          AND page_path IS NOT NULL AND page_path != ''
          AND (budget IS NULL OR budget = 0)
    """).fetchall()
    logger.info(f"重 parse 候选 (award + page_path + budget 空): {len(rows2)}")

    filled = 0
    skipped = 0
    for r in rows2:
        try:
            text = Path(r["page_path"]).read_text(encoding="utf-8", errors="replace")
            enriched = parse_html_detail(text, "award")
            new_budget = enriched.get("budget")
            if new_budget:
                conn.execute("""
                    UPDATE notices SET budget=?, budget_unit=?, budget_text=?
                    WHERE id=?
                """, (new_budget, enriched.get("budget_unit"), enriched.get("budget_text"), r["id"]))
                filled += 1
            else:
                skipped += 1
        except Exception as e:
            logger.debug(f"  {r['id'][:8]} 重 parse 失败: {e}")
            skipped += 1

    conn.commit()
    logger.info(f"\n=== 重 parse 写入: {filled} 条 (P1-7 排除后未误匹配), 跳过 {skipped} 条 ===")

    # 修复后
    post_total = conn.execute("SELECT COUNT(*) FROM notices WHERE notice_type='award'").fetchone()[0]
    post_budget = conn.execute("SELECT COUNT(*) FROM notices WHERE notice_type='award' AND budget IS NOT NULL AND budget>0").fetchone()[0]
    logger.info(f"\n[修复后] award 类: 总 {post_total} 条, budget 不空 {post_budget} 条")
    logger.info(f"[对比] award 类 budget: {pre_budget} → {post_budget} ({pre_budget - post_budget:+d} 条)")
    if pre_budget > post_budget:
        logger.info(f"✅ 清理掉 {pre_budget - post_budget} 条误匹配 (清空未补回)")

    # 全站 budget
    all_budget = conn.execute("SELECT COUNT(*) FROM notices WHERE budget IS NOT NULL AND budget>0").fetchone()[0]
    all_total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    logger.info(f"\n[全站 budget] {all_budget}/{all_total} = {all_budget/all_total*100:.1f}%")


if __name__ == "__main__":
    main()

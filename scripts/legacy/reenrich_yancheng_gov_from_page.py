#!/usr/bin/env python3
"""
reenrich_yancheng_gov_from_page.py — 2026-06-25 审计 P1-4/5/6 修复验证
================================================================
对 yancheng_gov.db 里 page_path 存在但关键字段空的记录,
用 parse_html_detail 重新解析 MD 文本, 写回 DB.

支持 dry-run, 加 --confirm 才真写.

用法:
  python3 reenrich_yancheng_gov_from_page.py            # dry-run
  python3 reenrich_yancheng_gov_from_page.py --confirm  # 真写
  python3 reenrich_yancheng_gov_from_page.py --field purchaser  # 只补 purchaser
  python3 reenrich_yancheng_gov_from_page.py --limit 100  # 只处理 100 条
"""
import argparse
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"

FIELDS_TO_CHECK = ["purchaser", "budget", "winner", "open_date"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="真写 DB")
    parser.add_argument("--field", choices=FIELDS_TO_CHECK, help="只补指定字段")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 条")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from enrich_details import parse_html_detail

    db_path = DATA_DIR / "yancheng_gov.db"
    if not db_path.exists():
        logger.error(f"DB 不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 找 page_path 存在 + 关键字段有缺失 的记录
    target_fields = [args.field] if args.field else FIELDS_TO_CHECK
    cond_empty = " OR ".join(f"({f} IS NULL OR {f}='')" for f in target_fields)
    where = f"WHERE page_path IS NOT NULL AND page_path != '' AND ({cond_empty})"
    sql = f"SELECT id, notice_type, project_name, page_path, {','.join(target_fields)} FROM notices {where}"
    if args.limit:
        sql += f" LIMIT {args.limit}"

    rows = conn.execute(sql).fetchall()
    total = len(rows)
    logger.info(f"候选记录 (有 page_path + 缺 {target_fields}): {total}")

    if total == 0:
        logger.info("✅ 没有需要补救的记录")
        sys.exit(0)

    stats = {"hit": 0, "miss": 0, "err": 0, "filled": {f: 0 for f in target_fields}}
    updates = []  # (id, fill_fields_dict)

    for r in rows:
        rid = r["id"]
        ntype = r["notice_type"] or "tender"
        pp = r["page_path"]
        try:
            text = Path(pp).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"  {rid[:8]} 读 MD 失败: {e}")
            stats["err"] += 1
            continue

        try:
            enriched = parse_html_detail(text, ntype)
        except Exception as e:
            logger.debug(f"  {rid[:8]} parse 失败: {e}")
            stats["err"] += 1
            continue

        # 找新解析有值但 DB 为空的字段
        fill = {}
        for f in target_fields:
            new_val = enriched.get(f)
            old_val = r[f] if f in r.keys() else None
            if new_val and (old_val is None or old_val == ""):
                fill[f] = new_val
                stats["filled"][f] += 1

        if not fill:
            stats["miss"] += 1
        else:
            updates.append((rid, fill))
            stats["hit"] += 1

    # 打印统计
    logger.info(f"\n=== 解析统计 ===")
    logger.info(f"  命中 (有字段可补): {stats['hit']}")
    logger.info(f"  未命中 (新解析没值): {stats['miss']}")
    logger.info(f"  错误 (读/解析失败): {stats['err']}")
    for f, n in stats["filled"].items():
        if n > 0:
            logger.info(f"    {f:<12} +{n} 条")

    if updates:
        logger.info(f"\n=== 待更新样例（前 5 条） ===")
        for rid, fs in updates[:5]:
            logger.info(f"  {rid[:8]}  {fs}")

    if not args.confirm:
        logger.info(f"\n[DRY-RUN] 加 --confirm 才真写 DB")
        sys.exit(0)

    # 真写
    logger.info(f"\n=== 开始 UPDATE ({len(updates)} 条) ===")
    conn.execute("BEGIN")
    for rid, fs in updates:
        sets = ", ".join(f"{k}=?" for k in fs)
        vals = list(fs.values()) + [rid]
        conn.execute(f"UPDATE notices SET {sets} WHERE id=?", vals)
    conn.commit()
    logger.info(f"✅ 已写入 {len(updates)} 条")

    # 复查
    logger.info(f"\n=== 复查 {target_fields} 填充率 ===")
    total_all = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    for f in target_fields:
        n = conn.execute(f"SELECT COUNT(*) FROM notices WHERE {f} IS NOT NULL AND {f}!=''").fetchone()[0]
        logger.info(f"  {f:<12} {n}/{total_all} = {n/total_all*100:.1f}%")


if __name__ == "__main__":
    main()

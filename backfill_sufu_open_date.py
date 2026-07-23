#!/usr/bin/env python3
"""
backfill_sufu_open_date.py — 回填 sufu.db tender.open_date 缺失值

【2026-07-23 P0-1】小标
背景: sufu 列表 API 返回字段叫 full_record.tenderStartTime, 但 sufu.py/sufu_parser 都找错 key
      导致 7 月新采 58 条 tender + 部分 6 月历史数据的 open_date 全空
功能: 用 sufu_parser.enrich_from_raw_json 跑一遍, 把能填的全部填上
      dry-run 默认开, --commit 才写库
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
from sufu_parser import enrich_from_raw_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="实际写库 (默认 dry-run)")
    parser.add_argument("--db", default="data/sufu.db", help="sufu 数据库路径")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 找 tender+open_date 空 + raw_json 有 tenderStartTime 的记录
    q = """
    SELECT * FROM notices
    WHERE notice_type = 'tender'
      AND (open_date IS NULL OR open_date = '')
      AND json_extract(raw_json, '$.full_record.tenderStartTime') IS NOT NULL
    """
    rows = cur.execute(q).fetchall()
    total = len(rows)
    print(f"[backfill] 候选 {total} 条 tender")

    updates = []
    skipped = 0
    for r in rows:
        out = enrich_from_raw_json(r["raw_json"], r)
        new_open_date = out.get("open_date")
        cur_open_date = r["open_date"]
        if not new_open_date or new_open_date == cur_open_date:
            skipped += 1
            continue
        updates.append((new_open_date, r["id"]))

    print(f"[backfill] 计划更新 {len(updates)} 条 (跳过 {skipped} 条 = 时间已一致)")
    if not args.commit:
        print(f"[dry-run] 不写库。示例 5 条:")
        for u in updates[:5]:
            print(f"  {u[1][:16]}... -> {u[0]}")
        print(f"\n[确认后跑] python3 {Path(__file__).name} --commit")
        return

    # 实际写库
    cur.executemany("UPDATE notices SET open_date = ? WHERE id = ?", updates)
    conn.commit()
    print(f"[backfill] ✅ 写库成功: {len(updates)} 条 open_date 已回填")

    # 重新统计填充率
    q2 = """
    SELECT COUNT(*) total, COUNT(open_date) filled
    FROM notices WHERE notice_type='tender'
    """
    total, filled = cur.execute(q2).fetchone()
    rate = filled / total * 100 if total else 0
    print(f"[verify] tender.open_date: {filled}/{total} = {rate:.1f}%")


if __name__ == "__main__":
    main()

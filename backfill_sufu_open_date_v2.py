#!/usr/bin/env python3
"""
backfill_sufu_open_date_v2.py — 回填 sufu.db 历史迁移数据的 open_date

【2026-07-23 P0-2】小标 — 衔接 P0-1 修复后的二次扫尾
背景:
  - P0-1 修了 sufu_parser.py + backfill_v1, 把 7月新采的 72 条 tender.open_date 填上了
  - 还有 49 条是从 history.db 迁移来的老数据 (migrated_from='history.db'),
    raw_content 是 Python dict 字符串, 里面有 tenderStartTime 字段
  - 迁移脚本只把 raw_content 整个塞进 raw_json, 没拆 tenderStartTime → open_date
  - 字符串里有中文符号 ()「」 导致 ast.literal_eval 失败, 用正则提取

用法:
  python3 backfill_sufu_open_date_v2.py           # dry-run
  python3 backfill_sufu_open_date_v2.py --commit  # 实际写库
"""
import argparse
import re
import sqlite3


def extract_tender_start_time(raw_content: str):
    """从 Python dict 字符串里提取 'tenderStartTime': 'YYYY-MM-DD HH:MM'"""
    if not raw_content:
        return None
    m = re.search(r"'tenderStartTime'\s*:\s*'([\d\-: T]+)'", raw_content)
    if m:
        return m.group(1)
    # 也试引号变体
    m = re.search(r'"tenderStartTime"\s*:\s*"([\d\-: T]+)"', raw_content)
    if m:
        return m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--db", default="data/sufu.db")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 找 history.db 迁移过来的 tender + open_date 空
    q = """
    SELECT id, raw_json, open_date FROM notices
    WHERE notice_type='tender'
      AND (open_date IS NULL OR open_date='')
      AND json_extract(raw_json,'$.migrated_from')='history.db'
    """
    rows = cur.execute(q).fetchall()
    print(f"[backfill_v2] 候选 {len(rows)} 条 history.db 迁移数据")

    updates = []
    skipped = 0
    for r in rows:
        import json
        d = json.loads(r["raw_json"])
        raw_content = d.get("raw_content", "")
        ts = extract_tender_start_time(raw_content)
        if not ts:
            skipped += 1
            continue
        if ts == r["open_date"]:
            skipped += 1
            continue
        updates.append((ts, r["id"]))

    print(f"[backfill_v2] 计划更新 {len(updates)} 条 (跳过 {skipped} 条)")
    if not args.commit:
        for u in updates[:5]:
            print(f"  {u[1][:16]}... -> {u[0]}")
        print("\n[dry-run] 加 --commit 才写库")
        return

    cur.executemany("UPDATE notices SET open_date = ? WHERE id = ?", updates)
    conn.commit()
    print(f"[backfill_v2] ✅ 写库成功: {len(updates)} 条")

    # 重新统计
    q2 = "SELECT COUNT(*) total, COUNT(open_date) filled FROM notices WHERE notice_type='tender'"
    total, filled = cur.execute(q2).fetchone()
    rate = filled / total * 100 if total else 0
    print(f"[verify] tender.open_date: {filled}/{total} = {rate:.1f}%")


if __name__ == "__main__":
    main()

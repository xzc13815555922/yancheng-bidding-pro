#!/usr/bin/env python3
"""
reenrich_jszbcg_open_date.py — 2026-06-25 审计 P0-2 修复
================================================================
问题：jszbcg 站的 open_date 字段实际用的是 openBidTime（发布时间），
     1881 条"开标时间"全部失真，倒计时报告直接受影响。

修复：从已有 MD 文件（data/pages/jszbcg/*.md）里重新解析"开标时间/文件开启时间/开启时间"
     写回 open_date 字段，覆盖错误的 openBidTime。

策略：
  1. 只处理 tender 类（招标公告，本来就需要开标时间）
  2. 优先按"开标时间"匹配（最常见）；fallback 到"文件开启时间""开启时间"
  3. 解析成功 → UPDATE open_date；失败 → 保留原值（不破坏）
  4. 默认 dry-run，加 --confirm 才真写

用法：
  python3 reenrich_jszbcg_open_date.py            # dry-run，看会改多少条
  python3 reenrich_jszbcg_open_date.py --confirm  # 真写
"""
import argparse
import logging
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"

# ── 真开标时间匹配模式（按优先级） ─────────────────────────────
# 注意：jszbcg 的 PDF 是图片型 → OCR 出来日期有空格，如 "2026 年 07 月 03 日 15 时 00 分"
# 正则要容错：年/月/日/时/分 与数字之间可能有空格
OPEN_DATE_PATTERNS = [
    # 1. 开标时间（含冒号/无冒号/带"为"字）— 容错 OCR 空格
    (re.compile(r'开标时间[为是]?\s*[：:]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?\s*(\d{1,2})\s*时\s*(\d{2})\s*分?'), "开标时间-OCR"),
    (re.compile(r'开标时间[为是]?\s*[：:]?\s*(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})日?\s*(\d{1,2})[时:：](\d{2})\s*分?'), "开标时间"),
    # 2. 文件开启时间
    (re.compile(r'文件开启时间[：:]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?\s*(\d{1,2})\s*时\s*(\d{2})\s*分?'), "文件开启时间-OCR"),
    (re.compile(r'文件开启时间[：:]?\s*(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})日?\s*(\d{1,2})[时:：](\d{2})\s*分?'), "文件开启时间"),
    # 3. 开启时间
    (re.compile(r'开启时间[：:]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?\s*(\d{1,2})\s*时\s*(\d{2})\s*分?'), "开启时间-OCR"),
    (re.compile(r'开启时间[：:]?\s*(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})日?\s*(\d{1,2})[时:：](\d{2})\s*分?'), "开启时间"),
    # 4. 开标日期（只有日期无时间 → 默认 09:00:00）
    (re.compile(r'开标日期[：:]?\s*(\d{4})[年\-]\s*(\d{1,2})[月\-]\s*(\d{1,2})日?'), "开标日期"),
]


def parse_open_date(text: str):
    """从 MD 文本里搜真开标时间，返回 (datetime_obj, matched_pattern_name, raw) 或 None。"""
    for pat, name in OPEN_DATE_PATTERNS:
        m = pat.search(text)
        if m:
            groups = m.groups()
            y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
            if len(groups) >= 5 and groups[3] and groups[4]:
                hh, mm = int(groups[3]), int(groups[4])
            else:
                # 只有日期，默认 09:00:00
                hh, mm = 9, 0
            try:
                return datetime(y, mo, d, hh, mm, 0), name, m.group(0)
            except ValueError:
                continue
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="真写 DB（不加只 dry-run）")
    args = parser.parse_args()

    db_path = DATA_DIR / "jszbcg.db"
    if not db_path.exists():
        logger.error(f"DB 不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 找 tender 类且有 page_path 的记录
    rows = conn.execute("""
        SELECT id, project_name, open_date, page_path
        FROM notices
        WHERE notice_type = 'tender'
          AND page_path IS NOT NULL
          AND page_path != ''
        ORDER BY id
    """).fetchall()
    total = len(rows)
    logger.info(f"候选 tender 记录（有 page_path）: {total}")

    stats = {"hit": 0, "miss": 0, "err": 0, "unchanged": 0, "changed": 0}
    updates = []  # (id, new_open_date, raw, pattern)

    for r in rows:
        rid = r["id"]
        old_od = r["open_date"]
        pp = r["page_path"]
        try:
            text = Path(pp).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"  {rid[:8]} 读 MD 失败: {e}")
            stats["err"] += 1
            continue

        result = parse_open_date(text)
        if not result:
            stats["miss"] += 1
            continue
        new_dt, pat_name, raw = result
        new_str = new_dt.strftime("%Y-%m-%d %H:%M:%S")
        stats["hit"] += 1
        if old_od == new_str:
            stats["unchanged"] += 1
        else:
            stats["changed"] += 1
            updates.append((rid, new_str, raw, pat_name))

    # 打印统计
    logger.info(f"\n=== 解析统计 ===")
    logger.info(f"  命中:    {stats['hit']:>5}")
    logger.info(f"  未命中:  {stats['miss']:>5}  (MD 里没找到真开标时间格式)")
    logger.info(f"  读错:    {stats['err']:>5}")
    logger.info(f"  等于原值: {stats['unchanged']:>5}  (新解析值 = openBidTime，覆盖了也无变化)")
    logger.info(f"  待更新:  {stats['changed']:>5}  (新解析值 ≠ openBidTime)")

    # 打印样例
    if updates:
        logger.info(f"\n=== 待更新样例（前 8 条） ===")
        for rid, nd, raw, pat in updates[:8]:
            logger.info(f"  {rid[:8]}  →  {nd}  (匹配: {pat}, 原文: {raw[:50]})")

    if not args.confirm:
        logger.info(f"\n[DRY-RUN] 加 --confirm 才真写 DB")
        sys.exit(0)

    # 真写
    logger.info(f"\n=== 开始 UPDATE ({len(updates)} 条) ===")
    conn.execute("BEGIN")
    for rid, nd, raw, pat in updates:
        conn.execute("UPDATE notices SET open_date=? WHERE id=?", (nd, rid))
    conn.commit()
    logger.info(f"✅ 已写入 {len(updates)} 条")

    # 复查
    new_have = conn.execute("SELECT COUNT(*) FROM notices WHERE notice_type='tender' AND open_date IS NOT NULL AND open_date != ''").fetchone()[0]
    logger.info(f"\n=== 复查 ===")
    logger.info(f"  tender open_date 非空: {new_have}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
reenrich_ycggzy_from_list_api.py — 2026-06-25 审计 P1-3 修复
========================================================================
问题: crawlers/ycggzy.py:611 显式 if k != "content" 把 content 字段排除出
     raw_json, 富化机会只有采集时一次, 漏抓永无补救。

修复策略:
  1. 历史 4050 条记录的 raw_json 没有 content 字段 (已存库, 改不回来了)
  2. 补救方式: 重发 ycggzy list API (分页 50/页) 拿回 content HTML
  3. 用 raw_json.code (item 的 id) 作为 key 匹配
  4. 调 _parse_ycggzy_content 重新解析 purchaser / winner / budget / open_date 等
  5. UPDATE DB + 把 content 写回 raw_json (以便以后再有正则调整能直接读)
  6. 默认 dry-run, 加 --confirm 才真写

用法:
  python3 reenrich_ycggzy_from_list_api.py            # dry-run
  python3 reenrich_ycggzy_from_list_api.py --confirm  # 真写
  python3 reenrich_ycggzy_from_list_api.py --limit 200  # 只补 200 条测试
"""
import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"

# ycggzy 列表 API
LIST_API = "https://ycggzy.jszwfw.gov.cn/cums/home/notice/noticePage"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://ycggzy.jszwfw.gov.cn/",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
}

PAGE_SIZE = 50

# ycggzy 采集器对 classCode 区分了 7 类, 都要补
CLASS_CODES = [
    "transactionInfo-1",  # 工程建设
    "transactionInfo-2",  # 交通工程
    "transactionInfo-3",  # 水利工程
    "transactionInfo-4",  # 政府采购
    "transactionInfo-5",  # 货物与服务
    "transactionInfo-7",  # 国有产权
]

import requests


def _fetch_list_page(session: requests.Session, class_code: str, page: int,
                     start_date: str, end_date: str) -> list:
    """调 list API 拿一页, 返回 items list。"""
    payload = {
        "size": PAGE_SIZE,
        "current": page,
        "classCode": class_code,
        "type": "transactionInfo",
        "start_date": start_date,
        "end_date": end_date,
    }
    try:
        resp = session.post(LIST_API, json=payload, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"  {class_code} 页{page}: HTTP {resp.status_code}")
            return []
        d = resp.json()
        return d.get("content", []) or []
    except Exception as e:
        logger.warning(f"  {class_code} 页{page} 异常: {e}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="真写 DB")
    parser.add_argument("--limit", type=int, default=0, help="只处理 N 条 (测试用)")
    args = parser.parse_args()

    # 延迟导入 ycggzy 内的解析器 (PaddleOCR 等重依赖不引入)
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "crawlers"))
    from crawlers.ycggzy import _parse_ycggzy_content  # noqa: E402
    from enrich_details import _parse_datetime  # noqa: E402

    db_path = DATA_DIR / "ycggzy.db"
    if not db_path.exists():
        logger.error(f"DB 不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 1. 找出 DB 中所有 ycggzy 记录的 code (raw_json.code = item id)
    logger.info("步骤 1/3: 加载 DB 中 ycggzy 记录的 code 索引")
    rows = conn.execute("""
        SELECT id, notice_type, project_name, purchaser, budget, winner, open_date, raw_json
        FROM notices
        WHERE detail_url IS NOT NULL
    """).fetchall()
    # code (item id) → DB row
    code_to_row = {}
    for r in rows:
        try:
            rj = json.loads(r["raw_json"] or "{}")
            code = rj.get("code")
            if code:
                code_to_row[code] = {
                    "id": r["id"],
                    "notice_type": r["notice_type"],
                    "project_name": r["project_name"],
                    "purchaser": r["purchaser"],
                    "budget": r["budget"],
                    "winner": r["winner"],
                    "open_date": r["open_date"],
                    "raw_json": rj,
                }
        except Exception:
            continue
    logger.info(f"  加载 {len(code_to_row)} 条记录的 code 索引")

    if args.limit:
        # 只保留前 N 个 code
        code_to_row = dict(list(code_to_row.items())[:args.limit])
        logger.info(f"  --limit {args.limit} 生效, 实际处理 {len(code_to_row)} 条")

    # 2. 按 publish_date 倒序分页拉 list API, 范围取所有 DB 记录的 min/max
    min_date = conn.execute("SELECT MIN(publish_date) FROM notices").fetchone()[0]
    max_date = conn.execute("SELECT MAX(publish_date) FROM notices").fetchone()[0]
    logger.info(f"步骤 2/3: 拉取 list API ({min_date} ~ {max_date}), 7 个 classCode")

    # 扩展日期范围 ±7 天防边界
    start_date = (datetime.strptime(min_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.strptime(max_date, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
    logger.info(f"  扩展日期范围: {start_date} ~ {end_date}")

    session = requests.Session()
    session.headers.update(HEADERS)

    found_codes = {}  # code → item dict (含 content)
    n_req = 0
    for cc in CLASS_CODES:
        page = 1
        while True:
            items = _fetch_list_page(session, cc, page, start_date, end_date)
            n_req += 1
            if not items:
                break
            for item in items:
                code = item.get("code")
                content = item.get("content")
                if code and content and code in code_to_row:
                    # 注意: 同一个 code 可能在不同 classCode 出现? 一般不会, 后到覆盖
                    found_codes[code] = item
            if len(items) < PAGE_SIZE:
                break
            page += 1
            time.sleep(0.3)  # 礼貌限流
        logger.info(f"  [{cc}] 拉完, 累计命中 {len(found_codes)}/{len(code_to_row)}")

    logger.info(f"  共发 {n_req} 次 list API 请求")
    logger.info(f"  命中 code: {len(found_codes)} / {len(code_to_row)} = "
                f"{len(found_codes)/len(code_to_row)*100:.1f}%")

    # 3. 对命中的 code 重解析 + UPDATE
    logger.info("步骤 3/3: 重解析 + UPDATE")
    stats = {"hit": 0, "miss": 0, "field_filled": {
        "purchaser": 0, "budget": 0, "winner": 0, "open_date": 0, "winning_amount": 0,
    }, "unchanged": 0}
    updates = []  # (id, fields_dict, new_raw_json)

    for code, item in found_codes.items():
        notice_type = code_to_row[code]["notice_type"]
        content_html = item.get("content") or ""
        if not content_html:
            stats["miss"] += 1
            continue
        try:
            enriched = _parse_ycggzy_content(content_html, notice_type) or {}
        except Exception as e:
            logger.debug(f"  parse failed {code[:8]}: {e}")
            stats["miss"] += 1
            continue

        # 收集有值的字段
        fields = {}
        for f in ("purchaser", "budget", "budget_unit", "budget_text",
                  "winner", "winning_amount", "open_date", "deadline", "expected_list"):
            v = enriched.get(f)
            if v is not None and v != "":
                fields[f] = v

        # 写回 raw_json (含 content, 永久解决 P1-3)
        new_rj = dict(item)  # 完整 item 已含 content

        # 找哪些字段 DB 当前空, 准备更新
        row = code_to_row[code]
        fill_fields = {}
        for f, v in fields.items():
            old = row.get(f)
            if (old is None or old == "") and v:
                fill_fields[f] = v
                stats["field_filled"][f] = stats["field_filled"].get(f, 0) + 1

        if not fill_fields:
            stats["unchanged"] += 1
        else:
            updates.append((row["id"], fill_fields, new_rj))
        stats["hit"] += 1

    # 打印统计
    logger.info(f"\n=== 解析统计 ===")
    logger.info(f"  命中 (找到 content): {stats['hit']}")
    logger.info(f"  未命中 (无 content 或解析失败): {stats['miss']}")
    logger.info(f"  字段已存在, 无需更新: {stats['unchanged']}")
    logger.info(f"  待更新 (有字段空 → 新解析有值): {len(updates)}")
    logger.info(f"  按字段:")
    for f, n in stats["field_filled"].items():
        if n > 0:
            logger.info(f"    {f:<15} +{n} 条")

    if updates:
        logger.info(f"\n=== 待更新样例（前 5 条） ===")
        for rid, fs, _ in updates[:5]:
            logger.info(f"  {rid[:8]}  {fs}")

    if not args.confirm:
        logger.info(f"\n[DRY-RUN] 加 --confirm 才真写 DB")
        sys.exit(0)

    # 真写
    logger.info(f"\n=== 开始 UPDATE ({len(updates)} 条) ===")
    conn.execute("BEGIN")
    for rid, fs, new_rj in updates:
        # 1) 更新字段
        sets = ", ".join(f"{k}=?" for k in fs)
        vals = list(fs.values()) + [rid]
        conn.execute(f"UPDATE notices SET {sets} WHERE id=?", vals)
        # 2) 更新 raw_json 含 content
        conn.execute("UPDATE notices SET raw_json=? WHERE id=?",
                     (json.dumps(new_rj, ensure_ascii=False), rid))
    conn.commit()
    logger.info(f"✅ 已写入 {len(updates)} 条 (+ 含 content 的 raw_json)")

    # 复查
    new_pc = conn.execute("SELECT COUNT(*) FROM notices WHERE purchaser IS NOT NULL AND purchaser != ''").fetchone()[0]
    new_bg = conn.execute("SELECT COUNT(*) FROM notices WHERE budget IS NOT NULL").fetchone()[0]
    new_wn = conn.execute("SELECT COUNT(*) FROM notices WHERE winner IS NOT NULL AND winner != ''").fetchone()[0]
    new_od = conn.execute("SELECT COUNT(*) FROM notices WHERE open_date IS NOT NULL AND open_date != ''").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    logger.info(f"\n=== 复查 ===")
    logger.info(f"  ycggzy 总: {total}")
    logger.info(f"  purchaser: {new_pc} ({new_pc/total*100:.1f}%)")
    logger.info(f"  budget:    {new_bg} ({new_bg/total*100:.1f}%)")
    logger.info(f"  winner:    {new_wn} ({new_wn/total*100:.1f}%)")
    logger.info(f"  open_date: {new_od} ({new_od/total*100:.1f}%)")


if __name__ == "__main__":
    main()

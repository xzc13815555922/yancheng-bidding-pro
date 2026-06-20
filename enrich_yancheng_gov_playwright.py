#!/usr/bin/env python3
"""
盐城市政府采购网 — Playwright 详情页补全
对 detail_fetched=2（requests 403）的记录，用 Playwright 抓页面 body.innerText 解析。
"""
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
from base import SiteDB
sys.path.insert(0, str(Path(__file__).parent))
from enrich_details import parse_html_detail

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SITE_KEY = "yancheng_gov"
DB_PATH = Path(__file__).parent / "data" / f"{SITE_KEY}.db"


def get_pending(limit=0):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    q = "SELECT id, detail_url, notice_type FROM notices WHERE detail_fetched != 1"
    if limit:
        q += f" LIMIT {limit}"
    rows = conn.execute(q).fetchall()
    conn.close()
    return rows


def update_record(rid: str, fields: dict, status: int):
    conn = sqlite3.connect(str(DB_PATH))
    sets, vals = [], []
    for k, v in fields.items():
        sets.append(f"{k}=?")
        vals.append(v)
    sets.append("detail_fetched=?")
    vals.append(status)
    vals.append(rid)
    conn.execute(f"UPDATE notices SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def print_stats():
    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    done  = conn.execute("SELECT COUNT(*) FROM notices WHERE detail_fetched=1").fetchone()[0]
    pc    = conn.execute("SELECT COUNT(*) FROM notices WHERE purchaser IS NOT NULL").fetchone()[0]
    bu    = conn.execute("SELECT COUNT(*) FROM notices WHERE budget IS NOT NULL").fetchone()[0]
    od    = conn.execute("SELECT COUNT(*) FROM notices WHERE open_date IS NOT NULL").fetchone()[0]
    dl    = conn.execute("SELECT COUNT(*) FROM notices WHERE deadline IS NOT NULL").fetchone()[0]
    conn.close()
    print(f"[{SITE_KEY}] total={total} done={done} | purchaser={pc} budget={bu} open_date={od} deadline={dl}")


def run(limit=0, concurrency=3):
    rows = get_pending(limit)
    logger.info(f"[{SITE_KEY}] 待补全: {len(rows)} 条")
    ok = fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        for i, row in enumerate(rows):
            rid        = row["id"]
            detail_url = row["detail_url"] or ""
            ntype      = row["notice_type"] or "tender"

            # 所有字段默认 NULL（防止残留）
            fields = {
                "purchaser": None, "budget": None, "budget_unit": None, "budget_text": None,
                "open_date": None, "deadline": None, "expected_list": None,
                "winner": None, "winning_amount": None,
            }
            status = 1

            if not detail_url:
                status = 2
            else:
                try:
                    page = context.new_page()
                    page.goto(detail_url, timeout=20000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    text = page.evaluate("() => document.body.innerText")
                    page.close()

                    found = parse_html_detail(text, ntype)
                    fields.update(found)

                    if i % 20 == 0:
                        logger.info(f"  {i+1}/{len(rows)} — {detail_url[:60]}")
                        logger.info(f"    found: {found}")
                except PWTimeout:
                    logger.debug(f"  超时: {detail_url[:60]}")
                    status = 2
                except Exception as e:
                    logger.debug(f"  异常: {e} | {detail_url[:60]}")
                    status = 2

            update_record(rid, fields, status)
            if status == 1:
                ok += 1
            else:
                fail += 1

            time.sleep(0.4)

        browser.close()

    logger.info(f"[{SITE_KEY}] 完成: 成功={ok} 失败={fail}")
    print_stats()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.stats:
        print_stats()
    else:
        run(limit=args.limit)

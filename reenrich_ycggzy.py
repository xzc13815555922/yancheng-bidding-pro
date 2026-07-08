#!/usr/bin/env python3
"""
ycggzy 重新补全：从列表 API 重取 content，用新解析函数更新 DB 中已有记录的
purchaser / budget / open_date / winner / winning_amount 字段。

由于 base.py 的 upsert 逻辑对 detail_fetched=1 的记录不更新补全字段，
本脚本直接 UPDATE。
"""
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
from base import DATA_DIR
from ycggzy import _parse_ycggzy_content, _map_notice_type, CLASS_CODES, HEADERS, LIST_API

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "ycggzy.db"
PAGE_SIZE = 100


def reenrich(start_date: str = "2026-06-01", end_date: str = "2026-06-19"):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    s = requests.Session()
    s.headers.update(HEADERS)

    # Build a map: detail_url → DB record id
    rows = conn.execute("SELECT id, detail_url, raw_json FROM notices").fetchall()
    id_by_url: dict = {}
    id_by_api_id: dict = {}
    for row in rows:
        if row["detail_url"]:
            id_by_url[row["detail_url"]] = row["id"]
        # raw_json has the API item id
        try:
            rj = json.loads(row["raw_json"] or "{}")
            api_id = rj.get("id")
            if api_id:
                id_by_api_id[str(api_id)] = row["id"]
        except Exception as e:
            logging.warning(f'[reenrich_ycggzy] L48 {e}')

    logger.info(f"DB记录: {len(rows)}条  url索引: {len(id_by_url)}  api_id索引: {len(id_by_api_id)}")

    updated = skipped = not_found = 0

    for class_code, class_name in CLASS_CODES:
        page = 1
        while True:
            payload = {
                "size": PAGE_SIZE, "current": page,
                "classCode": class_code, "type": "transactionInfo",
                "start_date": start_date, "end_date": end_date,
            }
            try:
                resp = s.post(LIST_API, json=payload, timeout=20)
                body = resp.json()
            except Exception as e:
                logger.warning(f"  [{class_name}] 页{page} 请求失败: {e}")
                break

            items = body.get("content", [])
            if not items:
                break

            for item in items:
                content_html = item.get("content") or ""
                type_name = item.get("typeName") or ""
                notice_type = _map_notice_type(type_name)
                api_id = str(item.get("id") or "")
                item_id = item.get("id")

                # Find DB record
                db_id = id_by_api_id.get(api_id)
                if not db_id:
                    # Try by detail_url
                    url = f"https://ycggzy.jszwfw.gov.cn/detail?id={item_id}" if item_id else ""
                    db_id = id_by_url.get(url)
                if not db_id:
                    not_found += 1
                    continue

                if not content_html:
                    skipped += 1
                    continue

                try:
                    fields = _parse_ycggzy_content(content_html, notice_type)
                except Exception as e:
                    logger.debug(f"  解析失败 {api_id}: {e}")
                    skipped += 1
                    continue

                if not fields:
                    skipped += 1
                    continue

                sets = [f"{k}=?" for k in fields]
                vals = list(fields.values()) + [db_id]
                conn.execute(
                    f"UPDATE notices SET {', '.join(sets)} WHERE id=?", vals
                )
                updated += 1

            conn.commit()
            logger.info(f"  [{class_name}] 页{page} 处理完 updated={updated} skip={skipped} not_found={not_found}")

            total_el = body.get("totalElements", 0)
            if page * PAGE_SIZE >= total_el:
                break
            page += 1
            time.sleep(0.5)

    conn.close()

    # Print final stats
    conn2 = sqlite3.connect(str(DB_PATH))
    total = conn2.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    print(f"\n=== ycggzy 字段填充率 (共{total}条) ===")
    for col, label in [('purchaser','发包单位'),('budget','预算'),('open_date','开标时间'),
                        ('winner','中标单位'),('winning_amount','中标金额')]:
        n = conn2.execute(f"SELECT COUNT(*) FROM notices WHERE {col} IS NOT NULL").fetchone()[0]
        print(f"  {label}: {n}/{total} ({n*100//total}%)")
    conn2.close()
    print(f"\n更新: {updated}  跳过: {skipped}  未匹配: {not_found}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2026-06-01")
    p.add_argument("--end", default="2026-06-19")
    args = p.parse_args()
    reenrich(args.start, args.end)

#!/usr/bin/env python3
"""
盐城市全域招标信息采集系统 Pro — 主入口
用法:
  python3 run_collection.py                    # 采集今天
  python3 run_collection.py --days 7           # 近7天
  python3 run_collection.py --start 2026-06-01 --end 2026-06-18
  python3 run_collection.py --site jszbcg      # 单站
  python3 run_collection.py --stats            # 仅统计
"""
import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from config import CRAWLERS

DATA_DIR = Path(__file__).parent / "data"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "run_collection.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def load_crawler(site_key: str, module_path: str, class_name: str):
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls()


def print_stats():
    sites = [row[0] for row in CRAWLERS]
    print(f"\n{'站':<14} {'条数':>6} {'发包单位':>8} {'预算':>6} {'开标时间':>8} {'中标单位':>8}")
    print("-" * 55)
    total_all = pc_all = bu_all = od_all = wi_all = 0
    for s in sites:
        db_path = DATA_DIR / f"{s}.db"
        if not db_path.exists():
            continue
        try:
            db = sqlite3.connect(str(db_path))
            total = db.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
            pc = db.execute("SELECT COUNT(*) FROM notices WHERE purchaser IS NOT NULL").fetchone()[0]
            bu = db.execute("SELECT COUNT(*) FROM notices WHERE budget IS NOT NULL").fetchone()[0]
            od = db.execute("SELECT COUNT(*) FROM notices WHERE open_date IS NOT NULL").fetchone()[0]
            wi = db.execute("SELECT COUNT(*) FROM notices WHERE winner IS NOT NULL").fetchone()[0]
            db.close()
            total_all += total; pc_all += pc; bu_all += bu; od_all += od; wi_all += wi
            print(f"{s:<14} {total:>6} {pc:>8} {bu:>6} {od:>8} {wi:>8}")
        except Exception as e:
            logger.warning(f'[print_stats_site_open] L60 {e}')
    print("-" * 55)
    print(f"{'合计':<14} {total_all:>6} {pc_all:>8} {bu_all:>6} {od_all:>8} {wi_all:>8}")


def _repair_derived_fields(site_filter: str = ""):
    """采集后从 raw_json 回填可推导但可能因历史缺失的字段。"""
    import json as _json

    # ycggzy: section ← raw_json.classCode
    if not site_filter or site_filter == "ycggzy":
        CODE_MAP = {
            "transactionInfo-1": "工程建设",
            "transactionInfo-2": "交通工程",
            "transactionInfo-3": "水利工程",
            "transactionInfo-4": "政府采购",
            "transactionInfo-5": "货物与服务",
            "transactionInfo-6": "土矿交易",
            "transactionInfo-7": "国有产权",
            "transactionInfo-9": "农业农村",
        }
        db_path = DATA_DIR / "ycggzy.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT id, raw_json FROM notices WHERE section IS NULL OR section=''"
            ).fetchall()
            updates = []
            for row_id, rj in rows:
                try:
                    code = _json.loads(rj).get("classCode", "")
                    sec = CODE_MAP.get(code)
                    if sec:
                        updates.append((sec, row_id))
                except Exception as e:
                    logger.warning(f'[print_stats_table_open] L95 {e}')
            if updates:
                conn.executemany("UPDATE notices SET section=? WHERE id=?", updates)
                conn.commit()
                logger.info(f"[ycggzy] section 回填 {len(updates)} 条")

            # notice_type_raw ← raw_json.typeName
            try:
                conn.execute("ALTER TABLE notices ADD COLUMN notice_type_raw TEXT")
                conn.commit()
            except Exception as e:
                logger.warning(f'[repair_derived_section] L106 {e}')
            rows2 = conn.execute(
                "SELECT id, raw_json FROM notices WHERE notice_type_raw IS NULL"
            ).fetchall()
            updates2 = []
            for row_id, rj in rows2:
                try:
                    v = _json.loads(rj).get("typeName")
                    if v:
                        updates2.append((v, row_id))
                except Exception as e:
                    logger.warning(f'[repair_derived_notice_type] L117 {e}')
            if updates2:
                conn.executemany("UPDATE notices SET notice_type_raw=? WHERE id=?", updates2)
                conn.commit()
                logger.info(f"[ycggzy] notice_type_raw 回填 {len(updates2)} 条")
            conn.close()


def run(start_date: str, end_date: str, site_filter: str = ""):
    results = {}
    for site_key, module_path, class_name in CRAWLERS:
        if site_filter and site_key != site_filter:
            continue
        logger.info(f"\n{'='*50}\n[{site_key}] 开始采集 {start_date} ~ {end_date}")
        t0 = time.time()
        try:
            crawler = load_crawler(site_key, module_path, class_name)
            r = crawler.crawl_all(start_date, end_date)
            elapsed = time.time() - t0
            total = r.get("total", 0)
            new = r.get("new", 0)
            logger.info(f"[{site_key}] 完成: total={total} new={new} 耗时{elapsed:.1f}s")
            results[site_key] = {"total": total, "new": new, "elapsed": elapsed}
        except Exception as e:
            logger.error(f"[{site_key}] 采集失败: {e}", exc_info=True)
            results[site_key] = {"error": str(e)}

    # 采集后修复：从 raw_json 回填可推导的字段
    _repair_derived_fields(site_filter)

    # 汇总
    logger.info("\n" + "="*50)
    logger.info("采集汇总:")
    grand_total = grand_new = 0
    for sk, r in results.items():
        if "error" in r:
            logger.info(f"  {sk}: 失败 — {r['error'][:60]}")
        else:
            logger.info(f"  {sk}: {r['total']}条 新增{r['new']}条 ({r['elapsed']:.1f}s)")
            grand_total += r["total"]
            grand_new += r["new"]
    logger.info(f"  总计: {grand_total}条 新增{grand_new}条")
    return results


def main():
    parser = argparse.ArgumentParser(description="盐城市全域招标信息采集 Pro")
    parser.add_argument("--start", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=1, help="采集最近N天（默认1=今天）")
    parser.add_argument("--site", help="只采集指定站点")
    parser.add_argument("--stats", action="store_true", help="仅显示统计")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    today = datetime.now().strftime("%Y-%m-%d")
    if args.start and args.end:
        start_date, end_date = args.start, args.end
    else:
        end_date = today
        start_date = (datetime.now() - timedelta(days=args.days - 1)).strftime("%Y-%m-%d")

    logger.info(f"采集范围: {start_date} ~ {end_date}")
    run(start_date, end_date, site_filter=args.site or "")
    print_stats()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()

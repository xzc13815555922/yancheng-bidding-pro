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

# 采集器注册表（site_key → crawler模块路径 + 类名）
CRAWLERS = [
    ("jszbcg",       "crawlers.jszbcg",          "JSZbcgCrawlerPro"),
    ("yancheng_gov", "crawlers.yancheng_gov",     "YanchengGovCrawlerPro"),
    ("ycggzy",       "crawlers.ycggzy",           "YcggzyCrawlerPro"),
    ("bigdata",      "crawlers.bigdata",          "BigdataCrawlerPro"),
    ("jingkai",      "crawlers.jingkai",          "JingkaiCrawlerPro"),
    ("kaifaqu",      "crawlers.chennan_kaifaqu",  "KaifaquCrawlerPro"),
    ("chennan",      "crawlers.chennan_kaifaqu",  "ChengnanCrawlerPro"),
    ("dongfang",     "crawlers.dongfang",         "DongfangCrawlerPro"),
    ("dushi",        "crawlers.dushi",            "DushiCrawlerPro"),
    ("jscn",         "crawlers.jscn",             "JscnCrawlerPro"),
    ("yueda",        "crawlers.yueda",            "YuedaCrawlerPro"),
    ("sufu",        "crawlers.sufu",             "SufuCrawlerPro"),
]

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
        except Exception:
            pass
    print("-" * 55)
    print(f"{'合计':<14} {total_all:>6} {pc_all:>8} {bu_all:>6} {od_all:>8} {wi_all:>8}")


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

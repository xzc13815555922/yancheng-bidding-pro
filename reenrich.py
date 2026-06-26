#!/usr/bin/env python3
"""
reenrich.py — 详情页补全调度入口

整合 4 个补全脚本，按正确顺序执行：
  1. enrich_details          — requests 补全（所有非 Playwright 站点）
  2. enrich_yancheng_gov     — Playwright 补全（yancheng_gov）
  3. enrich_jszbcg_ocr       — jszbcg PDF OCR 补全
  4. enrich_amendment_opendate — 更正公告 open_date 联动

用法：
  python3 reenrich.py                        # 仅 enrich_details（全站点）
  python3 reenrich.py --site jszbcg          # 仅 enrich_details 指定站点
  python3 reenrich.py --site yancheng_gov    # 仅 enrich_yancheng_gov（Playwright）
  python3 reenrich.py --ocr                  # 仅 enrich_jszbcg_ocr
  python3 reenrich.py --amendment            # 仅 enrich_amendment_opendate
  python3 reenrich.py --all                  # 全流程（1→2→3→4）
  python3 reenrich.py --stats                # 显示各站点字段覆盖率
  python3 reenrich.py --dry-run              # 不写库，仅打印
  python3 reenrich.py --force                # 强制重跑（含已完成）
  python3 reenrich.py --limit 20             # 每步最多处理 N 条（调试）
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logger = logging.getLogger(__name__)


def _run_details(site: str = "", dry_run: bool = False, limit: int = 0):
    """enrich_details.py — requests 补全"""
    from enrich_details import enrich_all, enrich_site
    if site and site != "all":
        logger.info(f"[details] 站点: {site}")
        enrich_site(site, limit=limit, dry_run=dry_run)
    else:
        logger.info("[details] 全站点")
        enrich_all(dry_run=dry_run)


def _run_yancheng_gov(dry_run: bool = False, force_all: bool = False, limit: int = 0):
    """enrich_yancheng_gov.py — Playwright 补全"""
    import asyncio
    from enrich_yancheng_gov import main as yg_main
    logger.info("[yancheng_gov] Playwright 补全")
    asyncio.run(yg_main(dry_run=dry_run, force_all=force_all, limit=limit))


def _run_ocr(limit: int = 0, force: bool = False):
    """enrich_jszbcg_ocr.py — jszbcg OCR"""
    import importlib
    ocr = importlib.import_module("enrich_jszbcg_ocr")
    logger.info("[jszbcg] OCR 补全")
    # 调用模块内的主入口（处理参数由调用方传递）
    ocr.run(limit=limit, force=force)


def _run_amendment(dry_run: bool = False):
    """enrich_amendment_opendate.py — 更正公告 open_date 联动"""
    from enrich_amendment_opendate import process_site, print_results, SITES
    mode = "DRY-RUN" if dry_run else "WRITE"
    logger.info(f"[amendment] 更正公告 open_date 联动 [{mode}]")
    grand = {"update": 0, "skip": 0, "multi": 0}
    for site in SITES:
        results = process_site(site, write=not dry_run)
        if results:
            grand["update"] += len(results.get("update", []))
            grand["skip"]   += len(results.get("skip", []))
            grand["multi"]  += len(results.get("multi", []))
    logger.info(
        f"[amendment] 写入={grand['update']} 跳过={grand['skip']} 多重候选={grand['multi']}"
    )


def _print_stats():
    """显示各站字段填充率（调用 enrich_details 的统计功能）"""
    from enrich_details import print_stats
    print_stats()


def _ocr_module_has_run():
    """检查 enrich_jszbcg_ocr 是否有 run() 函数"""
    try:
        import enrich_jszbcg_ocr
        return hasattr(enrich_jszbcg_ocr, "run")
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="详情页补全调度入口")
    parser.add_argument("--site", default="", help="站点 key（指定则只跑 enrich_details 该站）")
    parser.add_argument("--all", dest="run_all", action="store_true",
                        help="全流程：details → yancheng_gov → ocr → amendment")
    parser.add_argument("--ocr", action="store_true", help="仅运行 jszbcg OCR")
    parser.add_argument("--amendment", action="store_true", help="仅运行更正公告 open_date 联动")
    parser.add_argument("--stats", action="store_true", help="仅显示统计，不处理")
    parser.add_argument("--dry-run", action="store_true", help="不写库，仅打印")
    parser.add_argument("--force", action="store_true", help="强制重跑")
    parser.add_argument("--limit", type=int, default=0, help="每步最多处理条数（0=全部）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )

    if args.stats:
        _print_stats()
        return

    if args.ocr:
        if _ocr_module_has_run():
            _run_ocr(limit=args.limit, force=args.force)
        else:
            logger.warning("enrich_jszbcg_ocr 没有 run() 入口，请直接运行: python3 enrich_jszbcg_ocr.py")
        return

    if args.amendment:
        _run_amendment(dry_run=args.dry_run)
        return

    if args.run_all:
        # 全流程
        logger.info("=== 全流程补全 ===")
        _run_details(dry_run=args.dry_run, limit=args.limit)
        _run_yancheng_gov(dry_run=args.dry_run, force_all=args.force, limit=args.limit)
        if _ocr_module_has_run():
            _run_ocr(limit=args.limit, force=args.force)
        else:
            logger.info("[jszbcg] OCR：enrich_jszbcg_ocr.run() 不可用，跳过")
        _run_amendment(dry_run=args.dry_run)
        return

    # 默认：enrich_details
    if args.site == "yancheng_gov":
        _run_yancheng_gov(
            dry_run=args.dry_run, force_all=args.force, limit=args.limit
        )
    else:
        _run_details(site=args.site, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
从旧 history.db 迁移数据到 Pro 版各网站独立 DB。
用于：旧采集器已跑完 → 把结果按网站拆到 Pro DB 结构。
不覆盖 jszbcg/yancheng_gov（Pro 采集器已直接入库）。
"""
import json
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
from base import SiteDB, make_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OLD_DB = Path.home() / ".openclaw/plugin-skills/bidding-assistant/招投标数据/history.db"

# 旧 source_site → Pro site_key（跳过已有 Pro 采集器的站）
SITE_MAP = {
    "盐城市政府采购网":       None,        # Pro 采集器已处理
    "苏服采":                "sufu",
    "盐城市公共资源交易网":   "ycggzy",
    "江苏招标采购服务平台":   None,        # Pro 采集器已处理
    "城南新区公共资源交易网": "chennan",
    "开发区公共资源交易网":   "kaifaqu",
    "盐城市大数据集团":       "bigdata",
    "盐城市都市建设投资集团": "dushi",
    "盐城市东方集团":         "dongfang",
    "江苏世纪新城":           "jscn",
    "经开城发集团":           "jingkai",
    "悦达集团":              "yueda",
}

# 旧 project_type → notice_type（粗分，后续细化）
def map_notice_type(project_type: str) -> str:
    if not project_type:
        return "tender"
    t = project_type
    if any(k in t for k in ["中标", "成交", "候选"]):
        return "award"
    if any(k in t for k in ["意向", "预算", "需求"]):
        return "intention"
    if any(k in t for k in ["终止", "更正", "变更", "其他", "合同", "入围"]):
        return "other"
    return "tender"


def migrate(start_date: str = "2026-06-01", end_date: str = "2026-06-30"):
    if not OLD_DB.exists():
        logger.error(f"旧 DB 不存在: {OLD_DB}")
        return

    conn = sqlite3.connect(str(OLD_DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT * FROM bidding_projects WHERE date(publish_date) BETWEEN ? AND ?",
        (start_date, end_date)
    ).fetchall()
    logger.info(f"旧 DB 中 {start_date}~{end_date} 共 {len(rows)} 条")

    dbs: dict[str, SiteDB] = {}
    stats: dict[str, dict] = {}

    for row in rows:
        site_name = row["source_site"]
        site_key = SITE_MAP.get(site_name)
        if site_key is None:
            continue  # 跳过已有 Pro 采集器的站 / 未知站

        if site_key not in dbs:
            dbs[site_key] = SiteDB(site_key)
            stats[site_key] = {"total": 0, "new": 0}

        db = dbs[site_key]

        project_name = row["project_name"] or ""
        publish_date  = (row["publish_date"] or "")[:10]
        if not project_name or not publish_date:
            continue

        record_id = make_id(project_name, publish_date, site_name)
        notice_type = map_notice_type(row["project_type"] or "")

        record = {
            "id":            record_id,
            "site":          site_key,
            "notice_type":   notice_type,
            "source_url":    row["source_url"] or "",
            "detail_url":    row["detail_url"] or "",
            "publish_date":  publish_date,
            "project_name":  project_name,
            "budget":        row["budget"],
            "budget_text":   row["budget_text"],
            "budget_unit":   row["budget_unit"],
            "purchaser_raw": row["purchaser"] or "",
            "open_date":     row["opening_time"] or None,
            "deadline":      row["deadline"] or None,
            "expected_list": None,
            "winner":        None,
            "winning_amount": None,
            "region":        row["region"] or "盐城市",
            "district_code": "",
            "raw_json":      json.dumps({
                "migrated_from": "history.db",
                "project_type":  row["project_type"],
                "region":        row["region"],
                "procurement_method": row["procurement_method"],
                "raw_content":   (row["raw_content"] or "")[:500],
                # 保存关键字段供 enrich 阶段读取（部分站 columns 由迁移直接填入）
                "budget":        row["budget"],
                "budget_text":   row["budget_text"],
                "budget_unit":   row["budget_unit"],
                "deadline":      row["deadline"],
                "opening_time":  row["opening_time"],
                "purchaser":     row["purchaser"],
            }, ensure_ascii=False),
        }

        stats[site_key]["total"] += 1
        if db.insert(record):
            stats[site_key]["new"] += 1

    for sk, db in dbs.items():
        db.close()

    logger.info("\n=== 迁移完成 ===")
    for sk, s in sorted(stats.items()):
        by_type = dbs[sk].db if hasattr(dbs[sk], "db") else None
        logger.info(f"  {sk}: 总计{s['total']}条 新增{s['new']}条")
        # 重新打开查统计
        db2 = SiteDB(sk)
        logger.info(f"       分类: {db2.count_by_type()}")


if __name__ == "__main__":
    from datetime import datetime
    end = datetime.now().strftime("%Y-%m-%d")
    migrate("2026-06-01", end)

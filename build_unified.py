#!/usr/bin/env python3
"""
build_unified.py — 将12个站点 DB 汇总为统一数据库

输出：data/unified.db，含3张表：
  tender    招标公告
  award     中标/成交公告
  intention 采购意向
"""
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
UNIFIED_DB = DATA_DIR / "unified.db"

SITES = [
    "jszbcg", "yancheng_gov", "ycggzy", "sufu",
    "yueda", "dushi", "jscn", "chennan",
    "dongfang", "bigdata", "jingkai", "kaifaqu",
]

# 网站名称映射
SITE_NAMES = {
    "jszbcg":       "江苏招标采购服务平台",
    "yancheng_gov": "盐城政府网",
    "ycggzy":       "盐城公共资源交易",
    "sufu":         "苏服务",
    "yueda":        "悦达",
    "dushi":        "都市招标",
    "jscn":         "江苏城南",
    "chennan":      "盐南高新区",
    "dongfang":     "东方招标",
    "bigdata":      "大数据平台",
    "jingkai":      "盐城经开区",
    "kaifaqu":      "盐城开发区",
}

DDL_TENDER = """
CREATE TABLE IF NOT EXISTS tender (
    id              TEXT PRIMARY KEY,
    site_name       TEXT,   -- 网站名称
    std_district    TEXT,   -- 标准区县
    proj_major_cat  TEXT,   -- 标准行业大类
    proj_minor_cat  TEXT,   -- 标准行业小类
    publish_date    TEXT,   -- 发布时间
    project_name    TEXT,   -- 项目名称
    purchaser       TEXT,   -- 发包单位
    budget          REAL,   -- 预算金额（元）
    open_date       TEXT,   -- 开标时间
    deadline        TEXT,   -- 报名截止时间
    detail_url      TEXT    -- 项目详情页链接
)
"""

DDL_AWARD = """
CREATE TABLE IF NOT EXISTS award (
    id              TEXT PRIMARY KEY,
    site_name       TEXT,
    std_district    TEXT,
    proj_major_cat  TEXT,
    proj_minor_cat  TEXT,
    publish_date    TEXT,
    project_name    TEXT,
    purchaser       TEXT,
    winner          TEXT,
    winning_amount  REAL,
    detail_url      TEXT
)
"""

DDL_INTENTION = """
CREATE TABLE IF NOT EXISTS intention (
    id              TEXT PRIMARY KEY,
    site_name       TEXT,
    std_district    TEXT,
    proj_major_cat  TEXT,
    proj_minor_cat  TEXT,
    publish_date    TEXT,
    project_name    TEXT,
    purchaser       TEXT,
    budget          REAL,
    expected_list   TEXT,
    detail_url      TEXT
)
"""

DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS tender_date     ON tender(publish_date)",
    "CREATE INDEX IF NOT EXISTS tender_district ON tender(std_district)",
    "CREATE INDEX IF NOT EXISTS tender_cat      ON tender(proj_major_cat)",
    "CREATE INDEX IF NOT EXISTS award_date      ON award(publish_date)",
    "CREATE INDEX IF NOT EXISTS award_district  ON award(std_district)",
    "CREATE INDEX IF NOT EXISTS award_cat       ON award(proj_major_cat)",
    "CREATE INDEX IF NOT EXISTS intention_date  ON intention(publish_date)",
]


def load_site(db_path: Path):
    tenders, awards, intentions = [], [], []
    if not db_path.exists():
        return tenders, awards, intentions

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM notices WHERE is_duplicate = 0").fetchall()

    for row in rows:
        r = dict(row)
        ntype = r.get("notice_type", "")
        site_name = SITE_NAMES.get(r.get("site", ""), r.get("site", ""))

        if ntype in ("tender", "requirement"):
            tenders.append((
                r.get("id"),
                site_name,
                r.get("std_district"),
                r.get("proj_major_cat"),
                r.get("proj_minor_cat"),
                r.get("publish_date"),
                r.get("project_name"),
                r.get("purchaser"),
                r.get("budget"),
                r.get("open_date"),
                r.get("deadline"),
                r.get("detail_url"),
            ))
        elif ntype == "award":
            awards.append((
                r.get("id"),
                site_name,
                r.get("std_district"),
                r.get("proj_major_cat"),
                r.get("proj_minor_cat"),
                r.get("publish_date"),
                r.get("project_name"),
                r.get("purchaser"),
                r.get("winner"),
                r.get("winning_amount"),
                r.get("detail_url"),
            ))
        elif ntype == "intention":
            intentions.append((
                r.get("id"),
                site_name,
                r.get("std_district"),
                r.get("proj_major_cat"),
                r.get("proj_minor_cat"),
                r.get("publish_date"),
                r.get("project_name"),
                r.get("purchaser"),
                r.get("budget"),
                r.get("expected_list"),
                r.get("detail_url"),
            ))

    conn.close()
    return tenders, awards, intentions


import re as _re

def _norm_award_name(name: str) -> str:
    """去重用标准化名：去掉末尾的 采购包N、标段N、中标公告/成交公告 等噪音后缀。"""
    n = name or ""
    n = _re.sub(r'\s*采购包\d+$', '', n).strip()
    n = _re.sub(r'\s*[（(]\s*\d+\s*[)）]$', '', n).strip()
    return n


def _award_score(rec: tuple) -> int:
    """字段完整度评分：无采购包后缀(+4) + winner(+2) + winning_amount(+1)。"""
    name   = rec[6] or ""
    winner = rec[8]
    amount = rec[9]
    no_pkg = 0 if _re.search(r'采购包\d+$', name) else 4
    return no_pkg + (2 if winner else 0) + (1 if amount is not None else 0)


def _dedup_awards(awards: list) -> tuple[list, int]:
    """
    跨站去重：同标准化项目名 + 发布日期，保留最优一条（优先无包号 + 字段完整）。
    返回 (去重后列表, 丢弃数量)
    """
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for rec in awards:
        key = (_norm_award_name(rec[6]), rec[5])   # (标准化名, publish_date)
        groups[key].append(rec)

    result = []
    dropped = 0
    for recs in groups.values():
        if len(recs) == 1:
            result.append(recs[0])
        else:
            best = max(recs, key=_award_score)
            result.append(best)
            dropped += len(recs) - 1
    return result, dropped


def build():
    if UNIFIED_DB.exists():
        UNIFIED_DB.unlink()

    uconn = sqlite3.connect(str(UNIFIED_DB))
    uconn.execute("PRAGMA journal_mode=WAL")
    uconn.execute(DDL_TENDER)
    uconn.execute(DDL_AWARD)
    uconn.execute(DDL_INTENTION)
    for idx in DDL_INDEXES:
        uconn.execute(idx)
    uconn.commit()

    total_t = total_a = total_i = 0
    all_awards = []

    for site in SITES:
        tenders, awards, intentions = load_site(DATA_DIR / f"{site}.db")
        uconn.executemany("INSERT OR REPLACE INTO tender VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", tenders)
        uconn.executemany("INSERT OR REPLACE INTO intention VALUES (?,?,?,?,?,?,?,?,?,?,?)", intentions)
        uconn.commit()
        all_awards.extend(awards)
        total_t += len(tenders)
        total_i += len(intentions)
        print(f"[{site:<12}] tender:{len(tenders):4}  award:{len(awards):4}  intention:{len(intentions):3}")

    deduped_awards, dropped = _dedup_awards(all_awards)
    uconn.executemany("INSERT OR REPLACE INTO award VALUES (?,?,?,?,?,?,?,?,?,?,?)", deduped_awards)
    uconn.commit()
    total_a = len(deduped_awards)

    uconn.close()
    print(f"\n=== unified.db 构建完成 ===")
    print(f"  招标公告:  {total_t}")
    print(f"  中标/成交: {total_a}（跨站去重丢弃 {dropped} 条）")
    print(f"  采购意向:  {total_i}")


if __name__ == "__main__":
    build()

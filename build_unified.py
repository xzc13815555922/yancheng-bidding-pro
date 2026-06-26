#!/usr/bin/env python3
"""
build_unified.py — 将12个站点 DB 汇总为统一数据库

输出：data/unified.db，含4张表：
  tender    招标公告
  award     中标/成交公告
  intention 采购意向
  other     流标/终止/更正等（含 notice_subtype 细分）
"""
import json as _json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
from html_common import classify_other_subtype
from config import SITES, SITE_NAMES

DATA_DIR = Path(__file__).parent / "data"
UNIFIED_DB = DATA_DIR / "unified.db"

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

DDL_OTHER = """
CREATE TABLE IF NOT EXISTS other (
    id              TEXT PRIMARY KEY,
    site_name       TEXT,
    notice_subtype  TEXT,   -- 流标废标 / 终止暂停 / 更正变更 / 合同履约 / 候选公示 / 其他
    std_district    TEXT,
    proj_major_cat  TEXT,
    proj_minor_cat  TEXT,
    publish_date    TEXT,
    project_name    TEXT,
    purchaser       TEXT,
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
    "CREATE INDEX IF NOT EXISTS other_date      ON other(publish_date)",
    "CREATE INDEX IF NOT EXISTS other_subtype   ON other(notice_subtype)",
    "CREATE INDEX IF NOT EXISTS other_district  ON other(std_district)",
]


def load_site(db_path: Path):
    tenders, awards, intentions, others = [], [], [], []
    if not db_path.exists():
        return tenders, awards, intentions, others

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM notices WHERE is_duplicate = 0").fetchall()

    # yancheng_gov 专项：art_20171_* 是公开招标的精简跳转页，open_date 全空，过滤掉
    _BAD_URL_PAT = _re.compile(r'art_20171_')

    for row in rows:
        r = dict(row)
        ntype = r.get("notice_type", "")
        site_name = SITE_NAMES.get(r.get("site", ""), r.get("site", ""))

        if r.get("site") == "yancheng_gov" and _BAD_URL_PAT.search(r.get("detail_url") or ""):
            continue

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
            elist_raw = r.get("expected_list") or ""
            # 展开批次意向：expected_list 为 JSON 数组时拆分为子项
            expanded = False
            if elist_raw and elist_raw.strip().startswith("["):
                try:
                    sub_items = _json.loads(elist_raw)
                    if isinstance(sub_items, list) and len(sub_items) > 1:
                        for sub in sub_items:
                            intentions.append((
                                f"{r.get('id')}_{sub.get('seq', 0)}",
                                site_name,
                                r.get("std_district"),
                                r.get("proj_major_cat"),
                                r.get("proj_minor_cat"),
                                r.get("publish_date"),
                                sub.get("name") or r.get("project_name"),
                                r.get("purchaser"),
                                sub.get("budget_yuan"),
                                sub.get("expected_month"),
                                r.get("detail_url"),
                            ))
                        expanded = True
                except Exception:
                    pass
            if not expanded:
                # 单项 JSON 数组 → 展开为单条（用 expected_month 作为 expected_list）
                single_month = None
                if elist_raw and elist_raw.strip().startswith("["):
                    try:
                        sub_items = _json.loads(elist_raw)
                        if isinstance(sub_items, list) and len(sub_items) == 1:
                            single_month = sub_items[0].get("expected_month")
                    except Exception:
                        pass
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
                    single_month or (elist_raw if not elist_raw.startswith("[") else None),
                    r.get("detail_url"),
                ))
        elif ntype == "other":
            name = r.get("project_name") or ""
            # 从 raw_json 提取 typeName 辅助分类（不同站点字段名不同）
            _rj = r.get("raw_json") or ""
            _type_hint = ""
            if _rj and "{" in _rj:
                import json as _json
                try:
                    _d = _json.loads(_rj)
                    _type_hint = str(_d.get("typeName") or _d.get("type_name") or "")
                except Exception:
                    pass
            others.append((
                r.get("id"),
                site_name,
                classify_other_subtype(name, _type_hint),
                r.get("std_district"),
                r.get("proj_major_cat"),
                r.get("proj_minor_cat"),
                r.get("publish_date"),
                name,
                r.get("purchaser"),
                r.get("detail_url"),
            ))

    conn.close()
    return tenders, awards, intentions, others


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
    uconn.execute(DDL_OTHER)
    for idx in DDL_INDEXES:
        uconn.execute(idx)
    uconn.commit()

    total_t = total_a = total_i = total_o = 0
    all_awards = []

    for site in SITES:
        tenders, awards, intentions, others = load_site(DATA_DIR / f"{site}.db")
        uconn.executemany("INSERT OR REPLACE INTO tender VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", tenders)
        uconn.executemany("INSERT OR REPLACE INTO intention VALUES (?,?,?,?,?,?,?,?,?,?,?)", intentions)
        uconn.executemany("INSERT OR REPLACE INTO other VALUES (?,?,?,?,?,?,?,?,?,?)", others)
        uconn.commit()
        all_awards.extend(awards)
        total_t += len(tenders)
        total_i += len(intentions)
        total_o += len(others)
        print(f"[{site:<12}] tender:{len(tenders):4}  award:{len(awards):4}  intention:{len(intentions):3}  other:{len(others):4}")

    deduped_awards, dropped = _dedup_awards(all_awards)
    uconn.executemany("INSERT OR REPLACE INTO award VALUES (?,?,?,?,?,?,?,?,?,?,?)", deduped_awards)
    uconn.commit()
    total_a = len(deduped_awards)

    uconn.close()
    print(f"\n=== unified.db 构建完成 ===")
    print(f"  招标公告:  {total_t}")
    print(f"  中标/成交: {total_a}（跨站去重丢弃 {dropped} 条）")
    print(f"  采购意向:  {total_i}")
    print(f"  流标/终止: {total_o}")

    import build_project_links as _bpl
    _bpl.build()


if __name__ == "__main__":
    build()

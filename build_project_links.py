#!/usr/bin/env python3
"""
build_project_links.py — 在 unified.db 里建立 tender×award 关联表

在 build_unified.py 之后运行，对 unified.db 做追加修改（不重建）。

输出：
  project_links 表   — award_id → tender_id 映射
  project_chain 视图 — 招标+中标全链路，含周期天数

用法:
  python3 build_project_links.py            # 全量构建
  python3 build_project_links.py --stats    # 仅打印匹配统计
"""
import argparse
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
UNIFIED_DB = DATA_DIR / "unified.db"

DDL_PROJECT_LINKS = """
CREATE TABLE IF NOT EXISTS project_links (
    award_id        TEXT PRIMARY KEY REFERENCES award(id),
    tender_id       TEXT REFERENCES tender(id),
    canonical_name  TEXT,
    match_type      TEXT,           -- exact / substring
    amendment_count INTEGER DEFAULT 0
)
"""

DDL_INDEX = "CREATE INDEX IF NOT EXISTS pl_tender ON project_links(tender_id)"

DDL_VIEW = """
CREATE VIEW IF NOT EXISTS project_chain AS
SELECT
    t.id            AS tender_id,
    t.project_name  AS tender_name,
    t.site_name,
    t.std_district,
    t.proj_major_cat,
    t.purchaser,
    t.budget,
    t.open_date,
    t.publish_date  AS tender_date,
    a.id            AS award_id,
    a.project_name  AS award_name,
    a.winner,
    a.winning_amount,
    a.publish_date  AS award_date,
    pl.match_type,
    pl.amendment_count,
    CAST(ROUND(julianday(a.publish_date) - julianday(t.publish_date)) AS INTEGER)
                    AS cycle_days
FROM project_links pl
JOIN tender t ON t.id = pl.tender_id
JOIN award  a ON a.id = pl.award_id
"""

_PREFIX = re.compile(r'^(?:【[^】]*】\s*)+')
_SUFFIX = re.compile(
    r'(?:招标|采购|竞争性谈判|竞争性磋商|询价|二次|重新招标)?公告\s*$'
    r'|中标公告\s*$|成交公告\s*$|结果公示\s*$|评标结果公示\s*$'
    r'|中标候选人(?:结果)?公示\s*$|候选人公示\s*$'
)


def _norm(name: str) -> str:
    n = (name or '').strip()
    n = _PREFIX.sub('', n).strip()
    n = _SUFFIX.sub('', n).strip()
    return re.sub(r'[\s　]+', '', n)


def _build_tender_index(conn):
    rows = conn.execute(
        "SELECT id, project_name, site_name, publish_date FROM tender"
    ).fetchall()
    idx = defaultdict(list)
    for r in rows:
        k = _norm(r['project_name'])
        if len(k) >= 8:
            idx[k].append(r)
    return idx


def _count_amendments(conn, canonical_name: str) -> int:
    return conn.execute(
        "SELECT count(*) FROM other WHERE notice_subtype='更正变更' "
        "AND project_name LIKE ?",
        (f'%{canonical_name[:20]}%',)
    ).fetchone()[0]


def _match_award(award, t_idx, t_idx_all):
    """
    返回 (tender_row, match_type) 或 (None, None)。
    消歧顺序：精确同站 > 精确最新 > 子串同站 > 子串最新。
    """
    akey = _norm(award['project_name'])
    apub = award['publish_date'] or ''
    asite = award['site_name'] or ''

    if len(akey) < 8:
        return None, None

    # 精确匹配
    if akey in t_idx:
        cands = [t for t in t_idx[akey] if (t['publish_date'] or '') <= apub]
        if cands:
            same = [t for t in cands if t['site_name'] == asite]
            pool = same if same else cands
            return max(pool, key=lambda t: t['publish_date'] or ''), 'exact'

    # 子串匹配（仅当 akey 长度 ≥ 12）
    if len(akey) < 12:
        return None, None

    hits = []
    for k, ts in t_idx_all.items():
        if akey in k or k in akey:
            valid = [t for t in ts if (t['publish_date'] or '') <= apub]
            if valid:
                hits.extend(valid)

    if not hits:
        return None, None

    same = [t for t in hits if t['site_name'] == asite]
    pool = same if same else hits
    return max(pool, key=lambda t: t['publish_date'] or ''), 'substring'


def build(stats_only: bool = False):
    if not UNIFIED_DB.exists():
        print("unified.db 不存在，请先运行 build_unified.py")
        return

    conn = sqlite3.connect(str(UNIFIED_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute(DDL_PROJECT_LINKS)
    conn.execute(DDL_INDEX)
    conn.execute("DROP VIEW IF EXISTS project_chain")
    conn.execute(DDL_VIEW)
    conn.commit()

    t_idx = _build_tender_index(conn)
    awards = conn.execute(
        "SELECT id, project_name, site_name, publish_date FROM award"
    ).fetchall()

    rows = []
    cnt = {'exact': 0, 'substring': 0, 'none': 0}

    for a in awards:
        tender, mtype = _match_award(a, t_idx, t_idx)
        if tender:
            canonical = _norm(a['project_name'])
            amend_n = _count_amendments(conn, canonical)
            rows.append((a['id'], tender['id'], canonical, mtype, amend_n))
            cnt[mtype] += 1
        else:
            cnt['none'] += 1

    total = len(awards)
    print(f"award 总数: {total}")
    print(f"  精确匹配: {cnt['exact']} ({cnt['exact']/total:.0%})")
    print(f"  子串匹配: {cnt['substring']} ({cnt['substring']/total:.0%})")
    print(f"  未匹配:   {cnt['none']} ({cnt['none']/total:.0%})")
    print(f"  含更正公告: {sum(r[4] for r in rows if r[4]>0)} 条关联有更正记录")

    if stats_only:
        conn.close()
        return

    conn.execute("DELETE FROM project_links")
    conn.executemany(
        "INSERT OR REPLACE INTO project_links VALUES (?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    print(f"\nproject_links 写入 {len(rows)} 条，project_chain 视图已更新。")


def report():
    """从 project_chain 输出招采分析报告。"""
    conn = sqlite3.connect(str(UNIFIED_DB))
    conn.row_factory = sqlite3.Row

    # 1. 整体覆盖
    total_award = conn.execute("SELECT count(*) FROM award").fetchone()[0]
    linked = conn.execute("SELECT count(*) FROM project_links WHERE tender_id IS NOT NULL").fetchone()[0]
    print(f"=== 招采链路覆盖 ===")
    print(f"  award 总数: {total_award}  已关联 tender: {linked} ({linked/total_award:.0%})")

    # 2. 周期分析（排除异常：cycle_days 在 1~365 之间）
    cycle = conn.execute("""
        SELECT
            count(*) as n,
            CAST(avg(cycle_days) AS INTEGER) as avg_d,
            CAST(min(cycle_days) AS INTEGER) as min_d,
            CAST(max(cycle_days) AS INTEGER) as max_d
        FROM project_chain
        WHERE cycle_days BETWEEN 1 AND 365
    """).fetchone()
    print(f"\n=== 招采周期（1-365天，共{cycle['n']}条）===")
    print(f"  均值: {cycle['avg_d']}天  最短: {cycle['min_d']}天  最长: {cycle['max_d']}天")

    # 3. 各站周期对比
    print(f"\n--- 各站平均周期 ---")
    rows = conn.execute("""
        SELECT site_name, count(*) as n,
               CAST(avg(cycle_days) AS INTEGER) as avg_d
        FROM project_chain
        WHERE cycle_days BETWEEN 1 AND 365
        GROUP BY site_name ORDER BY avg_d
    """).fetchall()
    for r in rows:
        print(f"  {r['site_name']:<18} {r['avg_d']:3}天  ({r['n']}条)")

    # 4. 中标折扣率（只取 ratio 在 0.3~1.5 之间的样本）
    ratio_stats = conn.execute("""
        SELECT
            count(*) as n,
            ROUND(avg(winning_amount*1.0/budget), 3) as avg_r,
            ROUND(min(winning_amount*1.0/budget), 3) as min_r,
            ROUND(max(winning_amount*1.0/budget), 3) as max_r
        FROM project_chain
        WHERE budget > 10000
          AND winning_amount IS NOT NULL
          AND winning_amount*1.0/budget BETWEEN 0.3 AND 1.5
    """).fetchone()
    if ratio_stats and ratio_stats['n']:
        print(f"\n=== 中标折扣率（{ratio_stats['n']}条，预算>1万且ratio 0.3-1.5）===")
        print(f"  均值: {ratio_stats['avg_r']:.1%}  区间: [{ratio_stats['min_r']:.1%}, {ratio_stats['max_r']:.1%}]")

    # 5. 含更正公告项目
    amend_stat = conn.execute("""
        SELECT count(*) as n, avg(amendment_count) as avg_a
        FROM project_chain WHERE amendment_count > 0
    """).fetchone()
    print(f"\n=== 含更正记录 ===")
    print(f"  含更正公告的链路: {amend_stat['n']} 条  平均更正次数: {amend_stat['avg_a']:.1f}")

    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true", help="仅打印匹配统计，不写库")
    parser.add_argument("--report", action="store_true", help="从已有 project_chain 输出分析报告")
    args = parser.parse_args()
    if args.report:
        report()
    else:
        build(stats_only=args.stats)


if __name__ == "__main__":
    main()

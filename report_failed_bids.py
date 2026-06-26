#!/usr/bin/env python3
"""
report_failed_bids.py — 流标/终止分析报告

从 unified.db 的 other 表读取，报告各维度的流标/终止情况。
用法:
  python3 report_failed_bids.py             # 控制台报告
  python3 report_failed_bids.py --csv       # 同时输出 CSV 到 output/
  python3 report_failed_bids.py --site ycggzy  # 限定某站点
  python3 report_failed_bids.py --start 2026-01-01 --end 2026-06-30
"""
import argparse
import csv
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
UNIFIED_DB = DATA_DIR / "unified.db"
OUTPUT_DIR = Path(__file__).parent / "output"

# 重点子类型：流标/废标 + 终止/暂停
FAILURE_SUBTYPES = {"流标废标", "终止暂停"}


def _where(site: str, start: str, end: str) -> tuple[str, list]:
    clauses, params = [], []
    if site:
        clauses.append("site_name = ?")
        params.append(site)
    if start:
        clauses.append("publish_date >= ?")
        params.append(start)
    if end:
        clauses.append("publish_date <= ?")
        params.append(end)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def report(site: str = "", start: str = "", end: str = "", csv_out: bool = False):
    if not UNIFIED_DB.exists():
        print("unified.db 不存在，请先运行 build_unified.py")
        return

    conn = sqlite3.connect(str(UNIFIED_DB))
    conn.row_factory = sqlite3.Row
    wh, params = _where(site, start, end)

    print("=" * 64)
    print("流标 / 终止分析报告")
    if site:
        print(f"  站点过滤: {site}")
    if start or end:
        print(f"  日期范围: {start or '...'} → {end or '...'}")
    print("=" * 64)

    # ── 1. 子类型总览 ──────────────────────────────────────────
    rows = conn.execute(
        f"SELECT notice_subtype, COUNT(*) n FROM other {wh} GROUP BY notice_subtype ORDER BY n DESC",
        params,
    ).fetchall()
    total_other = sum(r["n"] for r in rows)
    total_award = conn.execute(
        f"SELECT COUNT(*) FROM award {wh}", params
    ).fetchone()[0]
    total_failure = sum(r["n"] for r in rows if r["notice_subtype"] in FAILURE_SUBTYPES)

    print(f"\n【1】other 记录子类型分布（共 {total_other} 条）")
    for r in rows:
        bar = "█" * (r["n"] * 30 // (total_other or 1))
        marker = " ◀ 流标/终止" if r["notice_subtype"] in FAILURE_SUBTYPES else ""
        print(f"  {r['notice_subtype']:<8} {r['n']:5d} ({r['n']/total_other:.1%}) {bar}{marker}")

    failure_rate = total_failure / (total_failure + total_award) if (total_failure + total_award) else 0
    print(f"\n  中标/成交: {total_award}条")
    print(f"  流标/终止: {total_failure}条")
    print(f"  → 流标终止率 = {total_failure} / ({total_award}+{total_failure}) = {failure_rate:.1%}")

    # ── 2. 按站点流标率 ─────────────────────────────────────────
    print(f"\n【2】各站点流标终止率")
    site_other = conn.execute(
        f"""SELECT site_name, notice_subtype, COUNT(*) n FROM other {wh}
            GROUP BY site_name, notice_subtype""",
        params,
    ).fetchall()
    site_award = conn.execute(
        f"SELECT site_name, COUNT(*) n FROM award {wh} GROUP BY site_name",
        params,
    ).fetchall()

    site_fail = {}
    for r in site_other:
        if r["notice_subtype"] in FAILURE_SUBTYPES:
            site_fail[r["site_name"]] = site_fail.get(r["site_name"], 0) + r["n"]
    site_aw = {r["site_name"]: r["n"] for r in site_award}

    all_sites = sorted(set(list(site_fail.keys()) + list(site_aw.keys())))
    print(f"  {'站点':<18} {'中标':>6} {'流标/终止':>8} {'流标率':>7}")
    print(f"  {'-'*42}")
    for s in all_sites:
        aw = site_aw.get(s, 0)
        fa = site_fail.get(s, 0)
        rate = fa / (aw + fa) if (aw + fa) else 0
        flag = " ⚠" if rate > 0.15 else ""
        print(f"  {s:<18} {aw:>6} {fa:>8} {rate:>7.1%}{flag}")

    # ── 3. 月度趋势 ─────────────────────────────────────────────
    print(f"\n【3】月度趋势（流标+终止 vs 中标）")
    month_fail = conn.execute(
        f"""SELECT substr(publish_date,1,7) m, COUNT(*) n FROM other
            {wh + (' AND' if wh else 'WHERE')} notice_subtype IN ('流标废标','终止暂停')
            GROUP BY m ORDER BY m""",
        params,
    ).fetchall()
    month_aw = conn.execute(
        f"""SELECT substr(publish_date,1,7) m, COUNT(*) n FROM award {wh}
            GROUP BY m ORDER BY m""",
        params,
    ).fetchall()

    m_fail = {r["m"]: r["n"] for r in month_fail}
    m_aw   = {r["m"]: r["n"] for r in month_aw}
    all_months = sorted(set(list(m_fail.keys()) + list(m_aw.keys())))

    print(f"  {'月份':<9} {'中标':>6} {'流标/终止':>8} {'流标率':>7}")
    print(f"  {'-'*33}")
    for m in all_months:
        aw = m_aw.get(m, 0)
        fa = m_fail.get(m, 0)
        rate = fa / (aw + fa) if (aw + fa) else 0
        bar = "▓" * int(rate * 20)
        print(f"  {m:<9} {aw:>6} {fa:>8} {rate:>7.1%} {bar}")

    # ── 4. 分类流标率（只算有分类的记录）────────────────────────
    print(f"\n【4】行业大类流标率（前10）")

    def _q(table, extra_where, extra_params):
        """拼接带可选站点/日期过滤的查询，extra_where 追加 AND 子句。"""
        clauses, p = list(params), list(params)
        if wh:
            sql = f"SELECT proj_major_cat cat, COUNT(*) n FROM {table} {wh} AND {extra_where} GROUP BY cat"
            p = list(params)
        else:
            sql = f"SELECT proj_major_cat cat, COUNT(*) n FROM {table} WHERE {extra_where} GROUP BY cat"
            p = []
        return conn.execute(sql, p).fetchall()

    cat_fail_rows = conn.execute(
        f"""SELECT proj_major_cat cat, COUNT(*) n FROM other
            {wh + (' AND ' if wh else ' WHERE ')}
            notice_subtype IN ('流标废标','终止暂停') AND proj_major_cat IS NOT NULL
            GROUP BY cat ORDER BY n DESC LIMIT 20""",
        params,
    ).fetchall()
    cat_aw_rows = conn.execute(
        f"""SELECT proj_major_cat cat, COUNT(*) n FROM award
            {wh + (' AND ' if wh else ' WHERE ')}
            proj_major_cat IS NOT NULL GROUP BY cat""",
        params,
    ).fetchall()

    cat_aw_map = {r["cat"]: r["n"] for r in cat_aw_rows}
    rows_with_rate = []
    for r in cat_fail_rows:
        aw = cat_aw_map.get(r["cat"], 0)
        fa = r["n"]
        rate = fa / (aw + fa) if (aw + fa) else 0
        rows_with_rate.append((r["cat"], aw, fa, rate))

    rows_with_rate.sort(key=lambda x: -x[3])
    print(f"  {'行业大类':<12} {'中标':>6} {'流标/终止':>8} {'流标率':>7}")
    print(f"  {'-'*38}")
    for cat, aw, fa, rate in rows_with_rate[:10]:
        flag = " ⚠" if rate > 0.20 else ""
        print(f"  {cat:<12} {aw:>6} {fa:>8} {rate:>7.1%}{flag}")

    # ── 5. 高流标率采购单位（排除样本过少）──────────────────────
    print(f"\n【5】高流标率采购单位（流标+终止≥3条，前10）")
    purch_fail = conn.execute(
        f"""SELECT purchaser, COUNT(*) n FROM other
            {wh + (' AND ' if wh else ' WHERE ')}
            notice_subtype IN ('流标废标','终止暂停') AND purchaser IS NOT NULL
            GROUP BY purchaser HAVING n >= 3 ORDER BY n DESC LIMIT 20""",
        params,
    ).fetchall()
    purch_aw = conn.execute(
        f"""SELECT purchaser, COUNT(*) n FROM award
            {wh + (' AND ' if wh else ' WHERE ')}
            purchaser IS NOT NULL GROUP BY purchaser""",
        params,
    ).fetchall()

    purch_aw_map = {r["purchaser"]: r["n"] for r in purch_aw}
    purch_rows = []
    for r in purch_fail:
        aw = purch_aw_map.get(r["purchaser"], 0)
        fa = r["n"]
        rate = fa / (aw + fa) if (aw + fa) else 0
        purch_rows.append((r["purchaser"], aw, fa, rate))

    purch_rows.sort(key=lambda x: -x[3])
    print(f"  {'采购单位':<22} {'中标':>5} {'流标/终止':>8} {'流标率':>7}")
    print(f"  {'-'*46}")
    for name, aw, fa, rate in purch_rows[:10]:
        flag = " ⚠" if rate > 0.30 else ""
        print(f"  {name[:22]:<22} {aw:>5} {fa:>8} {rate:>7.1%}{flag}")

    conn.close()

    # ── CSV 输出 ─────────────────────────────────────────────────
    if csv_out:
        OUTPUT_DIR.mkdir(exist_ok=True)
        db = sqlite3.connect(str(UNIFIED_DB))
        db.row_factory = sqlite3.Row
        wh2, p2 = _where(site, start, end)
        all_rows = db.execute(
            f"""SELECT o.id, o.site_name, o.notice_subtype, o.std_district,
                       o.proj_major_cat, o.proj_minor_cat, o.publish_date,
                       o.project_name, o.purchaser, o.detail_url
                FROM other o {wh2} ORDER BY o.publish_date DESC""",
            p2,
        ).fetchall()
        db.close()

        suffix = f"_{site}" if site else ""
        out_path = OUTPUT_DIR / f"流标终止报告{suffix}.csv"
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "站点", "子类型", "区县", "行业大类", "行业小类",
                             "发布日期", "项目名称", "采购单位", "详情链接"])
            for r in all_rows:
                writer.writerow(list(r))
        print(f"\n📄 CSV 已输出: {out_path}  ({len(all_rows)} 条)")


def main():
    parser = argparse.ArgumentParser(description="流标/终止分析报告")
    parser.add_argument("--site", default="", help="限定站点名（中文，如 盐城市公共资源交易平台）")
    parser.add_argument("--start", default="", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--csv", action="store_true", help="同时输出 CSV")
    args = parser.parse_args()
    report(site=args.site, start=args.start, end=args.end, csv_out=args.csv)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
数据质量基线验证 — 每次 build_unified 后自动跑。
任何指标低于基线即 FAIL，打印差异后以非零状态退出。

基线含义：当前已知最低可接受水平，不是目标值。
低于基线 = 有解析器/采集器回归，必须排查。

字段分母说明（按 notice_type 过滤，指标更准确）：
  purchaser       — 全量记录
  budget          — notice_type='tender' 记录
  open_date       — notice_type='tender' 记录
  winner          — notice_type='award'  记录
  winning_amount  — notice_type='award'  记录
"""
import sqlite3
import sys
from pathlib import Path

from config import SITE_BASELINES, UNIFIED_BASELINES, FIELD_NOTICE_TYPE

DATA_DIR = Path(__file__).parent / "data"


def check_sites() -> list[str]:
    failures = []
    for site, baseline in SITE_BASELINES.items():
        db = DATA_DIR / f"{site}.db"
        if not db.exists():
            failures.append(f"FAIL [{site}] DB 文件不存在")
            continue
        conn = sqlite3.connect(str(db))
        total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]

        if total < baseline.get("count", 0):
            failures.append(
                f"FAIL [{site}] 记录数 {total} < 基线 {baseline['count']}"
            )

        for col in ("purchaser", "budget", "open_date", "winner", "winning_amount"):
            if col not in baseline:
                continue
            nt = FIELD_NOTICE_TYPE.get(col)
            if nt:
                denom = conn.execute(
                    f"SELECT COUNT(*) FROM notices WHERE notice_type=?"
                    , (nt,)).fetchone()[0]
                numer = conn.execute(
                    f"SELECT COUNT(*) FROM notices WHERE notice_type=? "
                    f"AND {col} IS NOT NULL AND {col}!=''",
                    (nt,)).fetchone()[0]
                label = f"{col}[{nt}]"
            else:
                denom = total
                numer = conn.execute(
                    f"SELECT COUNT(*) FROM notices WHERE {col} IS NOT NULL AND {col}!=''"
                ).fetchone()[0]
                label = col

            ratio = numer / denom if denom else 0
            if ratio < baseline[col]:
                failures.append(
                    f"FAIL [{site}] {label} {ratio:.1%} < 基线 {baseline[col]:.0%}"
                    f"  ({numer}/{denom})"
                )
        conn.close()
    return failures


def check_unified() -> list[str]:
    failures = []
    db = DATA_DIR / "unified.db"
    if not db.exists():
        return ["FAIL unified.db 不存在，请先运行 build_unified.py"]
    conn = sqlite3.connect(str(db))
    for tbl, baseline in UNIFIED_BASELINES.items():
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            if n < baseline:
                failures.append(
                    f"FAIL [unified.{tbl}] {n} 条 < 基线 {baseline} 条"
                )
        except Exception:
            failures.append(f"FAIL [unified] 表 {tbl} 不存在")
    conn.close()
    return failures


def check_invariants() -> list[str]:
    failures = []

    missing = [s for s in SITE_BASELINES if not (DATA_DIR / f"{s}.db").exists()]
    if missing:
        failures.append(f"FAIL [invariant] 缺少 DB: {missing}")

    site_non_other = 0
    for site in SITE_BASELINES:
        db = DATA_DIR / f"{site}.db"
        if db.exists():
            site_non_other += sqlite3.connect(str(db)).execute(
                "SELECT COUNT(*) FROM notices WHERE notice_type != 'other'"
            ).fetchone()[0]

    unified_db = DATA_DIR / "unified.db"
    if unified_db.exists():
        conn = sqlite3.connect(str(unified_db))
        unified_total = sum(
            conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("tender", "award", "intention")
            if conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
        )
        conn.close()
        if unified_total < site_non_other * 0.90:
            failures.append(
                f"FAIL [invariant] unified {unified_total} < 各站非other {site_non_other} x 90%"
            )

    return failures


def main():
    print("=" * 60)
    print("数据质量基线验证（字段指标已按 notice_type 精确计算）")
    print("=" * 60)

    failures = []
    failures += check_sites()
    failures += check_unified()
    failures += check_invariants()

    if failures:
        print(f"\n❌ {len(failures)} 项不达标：")
        for f in failures:
            print(f"  {f}")
        print()
        sys.exit(1)
    else:
        conn = sqlite3.connect(str(DATA_DIR / "unified.db"))
        tender = conn.execute("SELECT COUNT(*) FROM tender").fetchone()[0]
        award  = conn.execute("SELECT COUNT(*) FROM award").fetchone()[0]
        conn.close()
        site_total = sum(
            sqlite3.connect(str(DATA_DIR / f"{s}.db")).execute(
                "SELECT COUNT(*) FROM notices"
            ).fetchone()[0]
            for s in SITE_BASELINES
            if (DATA_DIR / f"{s}.db").exists()
        )
        print(f"✅ 全部通过  原始={site_total}  unified=tender:{tender}/award:{award}")
        sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
数据质量基线验证 — 每次 build_unified 后自动跑。
任何指标低于基线即 FAIL，打印差异后以非零状态退出。

基线含义：当前已知最低可接受水平，不是目标值。
低于基线 = 有解析器/采集器回归，必须排查。
"""
import sqlite3
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# ── 各站基线（count=最低记录数，ratio=最低填充率）──
SITE_BASELINES = {
    "jszbcg": {
        "count":     1300,
        "purchaser": 0.88,   # 历史补录数据填充率较低，实际~89.6%
        "budget":    0.28,   # OCR 提取，图片 PDF 覆盖率有限
        "winner":    0.35,
    },
    "yancheng_gov": {
        "count":     850,
        "purchaser": 0.94,
    },
    "ycggzy": {
        "count":     1280,
        "purchaser": 0.92,
    },
    "sufu": {
        "count":     190,
        "purchaser": 0.99,   # 纯 API，应接近 100%
        "budget":    0.99,
    },
    "yueda":    {"count": 80,  "purchaser": 0.85},
    "dongfang": {"count": 40,  "purchaser": 0.75},
    "jscn":     {"count": 38,  "purchaser": 0.85},
    "dushi":    {"count": 33,  "purchaser": 0.70},
    "chennan":  {"count": 28,  "purchaser": 0.85},
    "kaifaqu":  {"count": 28,  "purchaser": 0.70},
    "bigdata":  {"count": 9,   "purchaser": 0.90},
    "jingkai":  {"count": 2,   "purchaser": 0.60},
}

# ── unified.db 基线 ──
UNIFIED_BASELINES = {
    "tender":    1300,
    "award":     1300,
    "intention": 300,
}

# ── 不变量（布尔检查）──
INVARIANTS = [
    # unified.db 总数 ≥ 各站 DB 总和的 90%（允许少量重复剔除）
    "unified_coverage",
    # 无站点 DB 文件缺失
    "all_dbs_exist",
]


def check_sites() -> list[str]:
    failures = []
    for site, baseline in SITE_BASELINES.items():
        db = DATA_DIR / f"{site}.db"
        if not db.exists():
            failures.append(f"FAIL [{site}] DB 文件不存在")
            continue
        conn = sqlite3.connect(str(db))
        total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
        if total < baseline["count"]:
            failures.append(
                f"FAIL [{site}] 记录数 {total} < 基线 {baseline['count']}"
            )
        for col in ("purchaser", "budget", "winner", "open_date"):
            if col not in baseline:
                continue
            n = conn.execute(
                f"SELECT COUNT(*) FROM notices WHERE {col} IS NOT NULL AND {col}!=''"
            ).fetchone()[0]
            ratio = n / total if total else 0
            if ratio < baseline[col]:
                failures.append(
                    f"FAIL [{site}] {col} 填充率 {ratio:.1%} < 基线 {baseline[col]:.0%}"
                    f"  ({n}/{total})"
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

    # 所有 DB 存在
    missing = [s for s in SITE_BASELINES if not (DATA_DIR / f"{s}.db").exists()]
    if missing:
        failures.append(f"FAIL [invariant] 缺少 DB: {missing}")

    # unified 总数 >= 各站非 other 记录数 x 90%
    # (other 类型=流标/更正/终止，不进 unified；跨站去重约削减 8%)
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
    print("=" * 55)
    print("数据质量基线验证")
    print("=" * 55)

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
        # 打印简要通过信息
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

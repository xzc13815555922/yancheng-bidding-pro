#!/usr/bin/env python3
"""
P0-4 (2026-07-07): 把 12 个站 DB 从 journal_mode=delete 切到 WAL。

特性：
- 只动 12 个站 DB（不动 unified.db / tyc.db / 0 字节的 ybp.db）
- 幂等：跑第二次检测到已 wal 则 no-op，不重复 VACUUM
- 写日志到 logs/enable_wal_YYYYMMDD.log
- 输出每站切换前/后模式到 stdout + 日志
"""
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 12 个站 DB 列表（按 azE 6/22 派单指定）
SITES = [
    "jszbcg", "yancheng_gov", "ycggzy", "sufu", "yueda",
    "dushi", "jscn", "chennan", "dongfang", "bigdata",
    "jingkai", "kaifaqu",
]


def switch_one(site: str, log_fh) -> tuple[str, str, str]:
    """切换单个 DB 到 WAL。返回 (site, before, after)。"""
    db_path = DATA_DIR / f"{site}.db"
    if not db_path.exists():
        msg = f"[skip] {site}.db 不存在"
        log_fh.write(msg + "\n")
        print(msg)
        return (site, "MISSING", "MISSING")

    # 先看大小：0 字节的不处理（避免误伤 ybp.db 等占位）
    if db_path.stat().st_size == 0:
        msg = f"[skip] {site}.db 0 字节，跳过"
        log_fh.write(msg + "\n")
        print(msg)
        return (site, "EMPTY", "EMPTY")

    conn = sqlite3.connect(str(db_path))
    try:
        before = conn.execute("PRAGMA journal_mode").fetchone()[0]
        # 切换到 WAL
        after = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]

        if before == after:
            # 已 WAL 模式，幂等 no-op，不重复 VACUUM
            msg = f"[noop] {site:20s} before={before} after={after} (已是 WAL，不重复 VACUUM)"
        else:
            # 真的从 delete 切过来，跑一次 VACUUM 让 WAL 完整生效
            conn.execute("VACUUM")
            msg = f"[switch] {site:20s} before={before} after={after} (已 VACUUM)"
        log_fh.write(msg + "\n")
        print(msg)
        return (site, before, after)
    finally:
        conn.close()


def main():
    today = datetime.now().strftime("%Y%m%d")
    log_path = LOG_DIR / f"enable_wal_{today}.log"

    print(f"[enable_wal_mode] 日志 → {log_path}")
    print(f"[enable_wal_mode] 目标：{len(SITES)} 个站 DB")
    print("-" * 70)

    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"[enable_wal_mode] {datetime.now().isoformat()} 启动\n")
        log_fh.write(f"目标：{len(SITES)} 个站 DB\n")
        log_fh.write("-" * 70 + "\n")

        switched = 0
        noop = 0
        skipped = 0
        for site in SITES:
            _, before, after = switch_one(site, log_fh)
            if before == "MISSING" or before == "EMPTY":
                skipped += 1
            elif before == after:
                noop += 1
            else:
                switched += 1

        summary = f"\n[summary] 切换={switched}  noop={noop}  skipped={skipped}  total={len(SITES)}"
        log_fh.write(summary + "\n")
        print(summary)


if __name__ == "__main__":
    main()
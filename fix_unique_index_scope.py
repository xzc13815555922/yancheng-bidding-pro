#!/usr/bin/env python3
"""
fix_unique_index_scope.py — P0-1 迁移脚本 (2026-07-07)

功能：
  对 data/*.db 调整 idx_notices_detail_url UNIQUE INDEX 作用域
  - 白名单站（jszbcg / yancheng_gov / tyc）：保留 UNIQUE INDEX
  - 非白名单站：删除 UNIQUE INDEX（保持 idx_* 普通索引不受影响）

依据：
  base.py UNIQUE_INDEX_SITES 白名单常量（单一来源）

幂等：
  跑 2 次结果一致（已建/已删 都 no-op）

dry-run:
  python3 fix_unique_index_scope.py --dry-run

真跑:
  python3 fix_unique_index_scope.py

日志:
  logs/fix_unique_index_YYYYMMDD_HHMMSS.log
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "crawlers"))

from base import UNIQUE_INDEX_SITES  # noqa: E402

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

INDEX_NAME = "idx_notices_detail_url"
SKIP_DBS = {"unified.db", "ybp.db", "cookies.json"}


def log_file_path() -> Path:
    return LOG_DIR / f"fix_unique_index_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def index_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def is_unique_index(conn: sqlite3.Connection, name: str) -> bool:
    """SQLite 没直接的 is_unique 列，PRAGMA index_list 也不含；用 sql 字段兜底。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
        (name,),
    ).fetchone()
    if not row or not row[0]:
        return False
    return "UNIQUE" in row[0].upper()


def fix_one(db_path: Path, dry_run: bool) -> tuple[str, str, str]:
    """
    返回 (状态, 站点, 详情)
    状态: KEEP / DROP / CREATE / NOOP / ERROR / SKIP
    """
    site = db_path.stem
    if site in ("unified", "ybp"):
        return ("SKIP", site, "排除 (unified/ybp)")
    if site not in UNIQUE_INDEX_SITES and site != "tyc_awards":
        # 不是 UNIQUE_INDEX_SITES 也不需要建新索引，但要 DROP 已有 UNIQUE INDEX（如果有）
        pass

    if not db_path.exists():
        return ("SKIP", site, "DB 不存在")

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except Exception as e:
        return ("ERROR", site, f"连接失败: {e}")

    try:
        has_index = index_exists(conn, INDEX_NAME)
        is_unique = is_unique_index(conn, INDEX_NAME) if has_index else False

        if site == "tyc":
            # tyc.db 自建 schema，索引在 tyc_awards 表上，名称是 idx_tyc_detail_url
            tyc_index = "idx_tyc_detail_url"
            has_tyc = index_exists(conn, tyc_index)
            if has_tyc and not dry_run:
                # 保留 tyc 的 UNIQUE INDEX（tyc 是白名单站）
                pass
            return ("KEEP", site, "tyc 自建索引，跳过 notices 检查")

        if site in UNIQUE_INDEX_SITES:
            # 白名单站：期望保留/重建 UNIQUE INDEX
            if has_index and is_unique:
                return ("KEEP", site, "UNIQUE INDEX 已存在")
            elif has_index and not is_unique:
                if dry_run:
                    return ("DRY-DROP+CREATE", site, "存在非唯一索引，将删除并重建为 UNIQUE")
                conn.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
                conn.execute(
                    f"CREATE UNIQUE INDEX {INDEX_NAME} "
                    "ON notices(detail_url) WHERE detail_url IS NOT NULL"
                )
                conn.commit()
                return ("DROP+CREATE", site, "非唯一索引升级为 UNIQUE")
            else:
                if dry_run:
                    return ("DRY-CREATE", site, "将新建 UNIQUE INDEX")
                conn.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
                    "ON notices(detail_url) WHERE detail_url IS NOT NULL"
                )
                conn.commit()
                return ("CREATE", site, "新建 UNIQUE INDEX")
        else:
            # 非白名单站：期望删除 UNIQUE INDEX
            if has_index and is_unique:
                if dry_run:
                    return ("DRY-DROP", site, "将删除 UNIQUE INDEX（保留普通索引）")
                conn.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
                conn.commit()
                return ("DROP", site, "已删除 UNIQUE INDEX")
            elif has_index and not is_unique:
                return ("KEEP", site, "存在非唯一索引，按设计保留")
            else:
                return ("NOOP", site, "无需操作")
    except Exception as e:
        return ("ERROR", site, f"操作异常: {e}")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="P0-1 (2026-07-07) 迁移：UNIQUE INDEX 白名单化"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印动作，不改 DB"
    )
    args = parser.parse_args()

    log_path = log_file_path()
    log_lines = []

    def emit(line: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out = f"[{ts}] {line}"
        print(out)
        log_lines.append(out)

    emit("=" * 60)
    emit(f"fix_unique_index_scope.py — P0-1 (2026-07-07)")
    emit(f"模式: {'DRY-RUN' if args.dry_run else '真跑'}")
    emit(f"白名单: {sorted(UNIQUE_INDEX_SITES)}")
    emit(f"扫描目录: {DATA_DIR}")
    emit("=" * 60)

    db_files = sorted(
        f for f in DATA_DIR.iterdir()
        if f.is_file()
        and f.suffix == ".db"
        and f.name not in SKIP_DBS
    )

    # 统计
    counts = {"KEEP": 0, "DROP": 0, "CREATE": 0, "DROP+CREATE": 0, "NOOP": 0, "ERROR": 0, "SKIP": 0}
    dry_marker = "DRY-" if args.dry_run else ""

    print(f"\n{'状态':<14} {'站':<14} 详情")
    print("-" * 60)
    for db_path in db_files:
        status, site, detail = fix_one(db_path, args.dry_run)
        display_status = status if not status.startswith("DRY-") else status[4:]
        display_marker = "(dry) " if status.startswith("DRY-") else ""
        print(f"{display_status:<14} {site:<14} {display_marker}{detail}")
        emit(f"{status:<14} {site:<14} {detail}")
        counts[status.replace("DRY-", "")] = counts.get(status.replace("DRY-", ""), 0) + 1

    print("-" * 60)
    print(f"\n汇总:")
    print(f"  白名单站 (期望 UNIQUE): {sorted(UNIQUE_INDEX_SITES)}")
    print(f"  非白名单站 (期望无 UNIQUE): "
          f"{sorted(set(f.stem for f in db_files) - UNIQUE_INDEX_SITES)}")
    print(f"  KEEP:        {counts.get('KEEP', 0)}")
    print(f"  CREATE:      {counts.get('CREATE', 0)}")
    print(f"  DROP:        {counts.get('DROP', 0)}")
    print(f"  DROP+CREATE: {counts.get('DROP+CREATE', 0)}")
    print(f"  NOOP:        {counts.get('NOOP', 0)}")
    print(f"  SKIP:        {counts.get('SKIP', 0)}")
    print(f"  ERROR:       {counts.get('ERROR', 0)}")

    emit("")
    emit(f"KEEP={counts.get('KEEP', 0)} CREATE={counts.get('CREATE', 0)} "
         f"DROP={counts.get('DROP', 0)} DROP+CREATE={counts.get('DROP+CREATE', 0)} "
         f"NOOP={counts.get('NOOP', 0)} SKIP={counts.get('SKIP', 0)} ERROR={counts.get('ERROR', 0)}")

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"\n日志: {log_path}")

    if counts.get("ERROR", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
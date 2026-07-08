#!/usr/bin/env python3
"""
migrate_unified_schema.py — unified.db 正式 schema 迁移

历史背景：
- v2.6/v2.7 演进中给 tender/intention 加了 sme_target 列
- 旧方案：extract_sme_target.py 启动时 "if 'sme_target' not in cols: ALTER"
  → 散乱、缺审计、不知道还差哪些列
- 新方案：集中维护 SCHEMA_MIGRATIONS，新加列只 append 一条 tuple；每次启动检查
  schema_version 表，按需 ALTER

使用：
    python3 migrate_unified_schema.py --status   # 当前版本 + 待执行
    python3 migrate_unified_schema.py --dry-run  # 只看 diff 不真改
    python3 migrate_unified_schema.py             # 应用所有未执行的迁移
"""
import sqlite3
import sys
from pathlib import Path

# 注：migrate 脚本路径在项目根目录
ROOT = Path(__file__).parent.parent.parent
UNIFIED_DB = ROOT / "data" / "unified.db"


# 迁移历史（按 version 升序；新加列只 append tuple）
# sql_list: 该版本要执行的 SQL 列表（idempotent：列已存在会跳过）
SCHEMA_MIGRATIONS = [
    (1, "基础 4 表(tender/award/intention/other) + project_links + project_chain view"
        " — 已包含在 build_unified.py DDL，无需 ALTER", []),
    (2, "tender/intention 加 sme_target 列（v2.6 中小微专题）",
        [
            "ALTER TABLE tender ADD COLUMN sme_target TEXT",
            "ALTER TABLE intention ADD COLUMN sme_target TEXT",
        ]),
    # 未来 v3 加新列在这里 append，例如：
    # (3, "project_links 加 created_at DATETIME", [
    #     "ALTER TABLE project_links ADD COLUMN created_at DATETIME",
    # ]),
]


def get_current_version(conn) -> int:
    """从 schema_version 表读当前已应用最高版本；表不存在返回 0"""
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0  # 表不存在


def init_version_table(conn):
    """schema_version 表不存在则建；已存在不动"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT,
            applied_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def apply_migrations(conn, dry_run: bool = False) -> list:
    """
    应用所有未执行的迁移（version > current）。

    返回 [(version, description), ...] 本轮应用列表（含 dry-run 显示）。

    幂等：列已存在 ALTER 会抛 "duplicate column name"，自动跳过；
          同一脚本连跑 2 次不会创建重复迁移记录（version 是 PRIMARY KEY）。
    """
    init_version_table(conn)
    current = get_current_version(conn)
    applied = []

    for version, desc, sqls in SCHEMA_MIGRATIONS:
        if version <= current:
            continue  # 已应用过
        if dry_run:
            print(f"[DRY-RUN] 待应用 v{version}: {desc}  ({len(sqls)} 条 SQL)")
            applied.append((version, desc))
            continue
        print(f"应用 v{version}: {desc}")
        for sql in sqls:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as e:
                err = str(e)
                if "duplicate column" in err:
                    # 幂等兜底：表已加过（多见于跨 DB 重复应用）
                    print(f"  跳过（列已存在）: {sql}")
                    continue
                raise
        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (version, desc),
        )
        conn.commit()
        applied.append((version, desc))
    return applied


def show_status(conn):
    """打印当前版本 + 待执行迁移"""
    init_version_table(conn)
    current = get_current_version(conn)
    print(f"当前 schema version: v{current}")
    pending = [(v, d) for v, d, _ in SCHEMA_MIGRATIONS if v > current]
    print(f"待执行: {len(pending)} 条")
    for v, d in pending:
        print(f"  - v{v}: {d[:80]}")
    # 已应用记录
    if current > 0:
        rows = conn.execute(
            "SELECT version, description, applied_at FROM schema_version ORDER BY version"
        ).fetchall()
        print(f"\n已应用历史 ({len(rows)} 条):")
        for v, d, ts in rows:
            print(f"  v{v} ({ts}) {d[:80]}")


def main():
    dry_run = "--dry-run" in sys.argv
    show = "--status" in sys.argv

    if not UNIFIED_DB.exists():
        print(f"❌ {UNIFIED_DB} 不存在")
        sys.exit(1)

    conn = sqlite3.connect(str(UNIFIED_DB))
    try:
        if show:
            show_status(conn)
            return

        applied = apply_migrations(conn, dry_run)
        if not applied:
            print("✅ schema 已是最新（无待执行迁移）")
        else:
            print(f"✅ 已{'（dry-run）' if dry_run else ''}应用 {len(applied)} 条迁移: "
                  f"{[v for v, _ in applied]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
init_unified_audit.py — 创建 unified_audit 审计表（数据治理 P0-处-1）
依据 GB/T 36073-2018 DCMM 数据生存周期 + 数据审计要求

功能：
  - 在 unified.db 创建 unified_audit 表（仅追加，不修改）
  - 不影响现有 4 表（tender/award/intention/other）和 project_links
  - 可独立调用，也可被 build_unified.py 等脚本 import 后调用

表结构：
  audit_id     INTEGER PRIMARY KEY  自增主键
  ts           TEXT NOT NULL        时间戳（ISO 8601）
  table_name   TEXT NOT NULL        被审计表（tender/award/intention/other）
  record_id    TEXT NOT NULL        业务记录 ID
  field_name   TEXT NOT NULL        字段名
  old_value    TEXT                 变更前值（NULL = 新增）
  new_value    TEXT                 变更后值（NULL = 删除）
  op_type      TEXT NOT NULL        INSERT / UPDATE / DELETE
  source       TEXT                 变更来源（脚本名，如 build_unified.py）
  trace_id     TEXT                 跟踪 ID（可选，便于排查）

设计原则（不动现有流程）：
  - 仅新增表 schema，不动现有 5 表
  - 默认 INSERT OR IGNORE，幂等
  - 现有脚本不自动写审计（CEO 后续决定哪些脚本接入）
"""
import sqlite3
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
UNIFIED_DB = DATA_DIR / "unified.db"

DDL = """
CREATE TABLE IF NOT EXISTS unified_audit (
    audit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    record_id   TEXT NOT NULL,
    field_name  TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    op_type     TEXT NOT NULL CHECK (op_type IN ('INSERT','UPDATE','DELETE')),
    source      TEXT,
    trace_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_unified_audit_ts ON unified_audit(ts);
CREATE INDEX IF NOT EXISTS idx_unified_audit_record ON unified_audit(table_name, record_id);
CREATE INDEX IF NOT EXISTS idx_unified_audit_field ON unified_audit(table_name, field_name);
"""


def init_audit_table():
    """创建 unified_audit 表（幂等）"""
    if not UNIFIED_DB.exists():
        print(f"❌ unified.db 不存在: {UNIFIED_DB}")
        return 1
    conn = sqlite3.connect(str(UNIFIED_DB))
    try:
        conn.executescript(DDL)
        conn.commit()
        # 验证表已创建
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='unified_audit'"
        )
        if cur.fetchone():
            print(f"✅ unified_audit 表创建成功: {UNIFIED_DB}")
            # 显示索引
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='unified_audit'"
            ).fetchall()
            for idx in indexes:
                print(f"  📇 索引: {idx[0]}")
        else:
            print(f"❌ 创建失败")
            return 1
        conn.close()
        return 0
    except Exception as e:
        print(f"❌ 异常: {e}")
        conn.close()
        return 1


def write_audit(conn, table_name: str, record_id: str, field_name: str,
                old_value, new_value, op_type: str, source: str = "", trace_id: str = ""):
    """
    写一条审计记录（在事务中由 caller 调用）
    用法：
        conn = sqlite3.connect('data/unified.db')
        # ... 业务更新
        write_audit(conn, 'tender', record_id, 'budget', old_budget, new_budget, 'UPDATE', 'build_unified.py')
        conn.commit()
    """
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO unified_audit
           (ts, table_name, record_id, field_name, old_value, new_value, op_type, source, trace_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (ts, table_name, record_id, field_name,
         str(old_value) if old_value is not None else None,
         str(new_value) if new_value is not None else None,
         op_type, source, trace_id)
    )


def main():
    print("=" * 60)
    print("unified_audit 审计表初始化（数据治理 P0-处-1）")
    print("=" * 60)
    return init_audit_table()


if __name__ == "__main__":
    sys.exit(main())

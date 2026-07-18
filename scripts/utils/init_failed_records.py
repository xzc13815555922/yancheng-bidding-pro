#!/usr/bin/env python3
"""
init_failed_records.py — 创建 failed_records 失败隔离表（数据治理 P1-处-1）
依据 GB/T 36073-2018 DCMM 数据加工域 + 数据质量错误隔离要求

功能：
  - 在每站 .db 创建 failed_records 表
  - 解析失败的记录进入此表，不污染主表
  - 与 report_failed_bids.py 配合，可后续审计/重试

表结构：
  id          INTEGER PRIMARY KEY  自增主键
  ts          TEXT NOT NULL        时间戳
  site        TEXT NOT NULL        站点
  raw_url     TEXT                 原始 URL（解析失败的源）
  raw_html    TEXT                 原始 HTML（截断 4KB）
  error_msg   TEXT                 错误信息
  retry_count INTEGER DEFAULT 0    重试次数
  resolved    INTEGER DEFAULT 0    是否已解决（0=否，1=是）

设计原则（不动现有流程）：
  - 仅新增表，不动 notices 主表
  - 不接入 run-full-pipeline.sh（CEO 决定）
  - 提供 helper 函数给其他脚本调用
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

DDL = """
CREATE TABLE IF NOT EXISTS failed_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    site        TEXT NOT NULL,
    raw_url     TEXT,
    raw_html    TEXT,
    error_msg   TEXT,
    retry_count INTEGER DEFAULT 0,
    resolved    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_failed_records_site ON failed_records(site);
CREATE INDEX IF NOT EXISTS idx_failed_records_resolved ON failed_records(resolved);
"""


def init_for_site(site_key: str) -> bool:
    """为单站 db 初始化 failed_records 表"""
    db_path = DATA_DIR / f"{site_key}.db"
    if not db_path.exists():
        print(f"  ⚠️  {db_path} 不存在，跳过")
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        conn.executescript(DDL)
        conn.commit()
        # 验证
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='failed_records'"
        )
        if cur.fetchone():
            conn.close()
            return True
        conn.close()
        return False
    except Exception as e:
        print(f"  ❌ {site_key}: {e}")
        return False


def init_all_sites() -> int:
    """为所有站点 db 初始化 failed_records 表"""
    site_dbs = sorted(DATA_DIR.glob("*.db"))
    # 排除 unified.db 和 tyc.db（特殊）
    targets = [p for p in site_dbs if p.name != "unified.db"]
    success = 0
    print(f"📋 目标: {len(targets)} 个站点 db")
    for db_file in targets:
        site_key = db_file.stem
        if init_for_site(site_key):
            success += 1
            print(f"  ✅ {site_key}")
        else:
            print(f"  ⚠️ {site_key}")
    return success


def record_failure(site_key: str, raw_url: str, raw_html: str, error_msg: str):
    """记一条失败记录（在事务中由 caller 调用）"""
    db_path = DATA_DIR / f"{site_key}.db"
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO failed_records
           (ts, site, raw_url, raw_html, error_msg)
           VALUES (?,?,?,?,?)""",
        (datetime.now(timezone.utc).isoformat(), site_key, raw_url,
         raw_html[:4096] if raw_html else None, error_msg[:1000])
    )
    conn.commit()
    conn.close()


def main():
    print("=" * 60)
    print("failed_records 失败隔离表初始化（数据治理 P1-处-1）")
    print("=" * 60)
    n = init_all_sites()
    print()
    print(f"✅ 完成: {n} 个站点 db 初始化成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())

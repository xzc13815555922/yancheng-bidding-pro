#!/usr/bin/env python3
"""
init_feedback.py — 创建 feedback 用户反馈表（数据治理 P1-应-1）
依据 GB/T 36073-2018 DCMM 数据应用域 + 用户反馈闭环要求

功能：
  - 在 unified.db 创建 feedback 表
  - 关联到 unified.id（unified.id = notices.id = tender.id/award.id/intention.id/other.id）
  - 飞书群用户反馈可直接入表

表结构：
  feedback_id  INTEGER PRIMARY KEY  自增主键
  ts           TEXT NOT NULL        时间戳
  source       TEXT NOT NULL        反馈来源（feishu/email/manual）
  feishu_msg_id TEXT                飞书消息 ID（去重）
  sender       TEXT                 反馈人 open_id
  record_type  TEXT NOT NULL        关联表（tender/award/intention/other）
  record_id    TEXT NOT NULL        关联记录 ID
  category     TEXT                 问题分类（数据缺失/解析错误/重复/其他）
  message      TEXT                 反馈内容
  status       TEXT DEFAULT 'open'  open / resolved / rejected
  resolver     TEXT                 处理人
  resolved_at  TEXT                 处理时间

设计原则（不动现有流程）：
  - 仅新增表，不动其他表
  - 不接入任何 cron（CEO 后续决定）
"""
import sqlite3
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
UNIFIED_DB = DATA_DIR / "unified.db"

DDL = """
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    source         TEXT NOT NULL,
    feishu_msg_id  TEXT,
    sender         TEXT,
    record_type    TEXT NOT NULL,
    record_id      TEXT NOT NULL,
    category       TEXT,
    message        TEXT,
    status         TEXT DEFAULT 'open' CHECK (status IN ('open','resolved','rejected')),
    resolver       TEXT,
    resolved_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_record ON feedback(record_type, record_id);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_msg_unique ON feedback(feishu_msg_id) WHERE feishu_msg_id IS NOT NULL;
"""


def main():
    if not UNIFIED_DB.exists():
        print(f"❌ unified.db 不存在: {UNIFIED_DB}")
        return 1
    print("=" * 60)
    print("feedback 用户反馈表初始化（数据治理 P1-应-1）")
    print("=" * 60)
    conn = sqlite3.connect(str(UNIFIED_DB))
    try:
        conn.executescript(DDL)
        conn.commit()
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'")
        if cur.fetchone():
            print(f"✅ feedback 表创建成功")
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='feedback'"
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


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
test_incremental_collect.py — 烟雾测试, 锁定 incremental_collect 关键路径
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

import incremental_collect as ic


def test_detect_new_since_id_锚点():
    """BUG-4 防回归: id 锚点不被已存在 ID 误判为新."""
    with tempfile.TemporaryDirectory() as tmp:
        # 假数据: 一个 site db 含 3 条记录
        db_path = Path(tmp) / "sufu.db"
        c = sqlite3.connect(str(db_path))
        c.execute("""
            CREATE TABLE notices (
                id TEXT PRIMARY KEY,
                site TEXT, notice_type TEXT, publish_date TEXT,
                project_name TEXT, purchaser TEXT, detail_url TEXT,
                std_district TEXT, proj_major_cat TEXT, page_path TEXT,
                crawl_time TEXT, is_duplicate INTEGER DEFAULT 0
            )
        """)
        c.executemany(
            "INSERT INTO notices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("id001-old", "sufu", "tender", "2026-07-20", "old project",
                 "purchaser X", "https://x", "盐南", "工程", "/tmp/p.md",
                 "2026-07-20 10:00:00", 0),
                ("id002-yesterday", "sufu", "tender", "2026-07-22", "yesterday project",
                 "purchaser Y", "https://y", "盐南", "工程", "/tmp/p.md",
                 "2026-07-22 10:00:00", 0),
                ("id003-today", "sufu", "award", "2026-07-23", "today project",
                 "purchaser Z", "https://z", "经开", "服务", "/tmp/p.md",
                 "2026-07-23 10:00:00", 0),
            ],
        )
        c.commit()
        c.close()

        # 测试 1: 首次进来全 3 条都视为新增
        state = {}
        with patch.object(ic, "DATA_DIR", Path(tmp)):
            new = ic.detect_new_since(state)
        assert len(new) == 3, f"预期 3 条新增, 实际 {len(new)}"
        # 测试 2: state 已记录 3 个 id, 再进来应该空
        state2 = {"sufu": ["id001-old", "id002-yesterday", "id003-today"]}
        with patch.object(ic, "DATA_DIR", Path(tmp)):
            new2 = ic.detect_new_since(state2)
        assert len(new2) == 0, f"预期 0 条, 实际 {len(new2)}, 锚点 id 去重回归 BUG-4!"


def test_write_md_notify_按站分子目录():
    """md 按站分子目录, 永不覆盖."""
    with tempfile.TemporaryDirectory() as tmp:
        md_root = Path(tmp) / "md_notify"
        with patch.object(ic, "MD_NOTIFY_DIR", md_root):
            records = [
                {"site": "sufu", "site_name": "苏服务", "notice_type": "tender",
                 "publish_date": "2026-07-23", "project_name": "测试项目A",
                 "purchaser": "X 街道", "detail_url": "https://x", "page_path": "/tmp/p.md",
                 "std_district": "盐南", "proj_major_cat": "工程",
                 "id": "abcdef1234567890abcdef"},
                {"site": "yancheng_gov", "site_name": "盐城政采", "notice_type": "tender",
                 "publish_date": "2026-07-23", "project_name": "测试项目B",
                 "purchaser": "Y 单位", "detail_url": "https://y", "page_path": "/tmp/p.md",
                 "std_district": "经开", "proj_major_cat": "服务",
                 "id": "0987654321fedcba0987"},
            ]
            paths = ic.write_md_notify(records, "2026-07-23_1030")
            assert len(paths) == 2, f"预期 2 份 md, 实际 {len(paths)}"
            # 检查子目录结构
            assert paths[0].parent.name == "sufu"
            assert paths[1].parent.name == "yancheng_gov"
            # 检查文件名包含 项目名 + id 前缀
            assert "测试项目A" in paths[0].name or "测试项目A" in str(paths[0])
            assert "abcdef1234567890" in paths[0].name
            # 检查文件内容含关键字段
            content = paths[0].read_text()
            assert "X 街道" in content
            assert "盐南" in content
            assert "测试项目A" in content
        print(f"  PASS test_write_md_notify_按站子目录, 2 份 md 已写")


def test_render_batch_message_格式稳定():
    """检查消息模板不被无意改动."""
    records = [
        {"site": "sufu", "site_name": "苏服务", "notice_type": "tender",
         "publish_date": "2026-07-23", "project_name": "项目A",
         "purchaser": "X街道", "detail_url": "https://x", "page_path": "/tmp/p.md",
         "std_district": "盐南", "proj_major_cat": "工程", "id": "abc"},
    ]
    msg = ic.render_batch_message(records)
    assert "盐城招标增量" in msg
    assert "苏服务" in msg
    assert "X街道" in msg
    assert "https://x" in msg
    print("  PASS test_render_batch_message_格式稳定")


def test_load_save_state_幂等():
    """游标读写幂等."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "state.json"
        with patch.object(ic, "STATE_FILE", state_file):
            # 首次: 无文件 → 默认值
            s = ic.load_state()
            assert s.get("last_per_site_ids") == {}
            # 写
            s["last_per_site_ids"]["sufu"] = ["id1", "id2"]
            ic.save_state(s)
            # 再读 → 一致
            s2 = ic.load_state()
            assert s2["last_per_site_ids"]["sufu"] == ["id1", "id2"]
        print("  PASS test_load_save_state_幂等")


if __name__ == "__main__":
    test_detect_new_since_id_锚点()
    test_write_md_notify_按站分子目录()
    test_render_batch_message_格式稳定()
    test_load_save_state_幂等()
    print("\n✅ 全 4 项烟雾测试通过")

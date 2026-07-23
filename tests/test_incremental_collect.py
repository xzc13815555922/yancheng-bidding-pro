#!/usr/bin/env python3
"""
test_incremental_collect.py — 烟雾测试 (4 项, 2026-07-23 P0-需求)

锁定内容:
1. id 锚点去重 (BUG-4 防回归)
2. md 按站子目录落盘 (老板 2026-07-23 要求)
3. 群通报格式 = 网站 + 项目 + 金额 (老板 2026-07-23 最新要求)
4. 盐南/经开未分类项目过滤逻辑
"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

import incremental_collect as ic


def test_is_target_district():
    """老板要求群通报只推盐南/经开且未分类项目."""
    # 命中
    assert ic.is_target_district({"std_district": "盐南高新区", "proj_major_cat": None}) is True
    assert ic.is_target_district({"std_district": "盐南", "proj_major_cat": None}) is True
    assert ic.is_target_district({"std_district": "经开区", "proj_major_cat": None}) is True
    assert ic.is_target_district({"std_district": "盐城经开区", "proj_major_cat": None}) is True
    assert ic.is_target_district({"std_district": "经开区行政审批局公共资源交易服务平台", "proj_major_cat": None}) is True
    # miss 行政区
    assert ic.is_target_district({"std_district": "亭湖区", "proj_major_cat": None}) is False
    assert ic.is_target_district({"std_district": "盐都区", "proj_major_cat": None}) is False
    assert ic.is_target_district({"std_district": "大丰区", "proj_major_cat": None}) is False
    # 已分类项目 → 不推
    assert ic.is_target_district({"std_district": "盐南高新区", "proj_major_cat": "工程类"}) is False
    assert ic.is_target_district({"std_district": "经开区", "proj_major_cat": "服务类"}) is False
    print("  PASS test_is_target_district")


def test_format_amount():
    """金额格式化: 元/万元/亿元 各种场景."""
    # 元
    assert "元" in ic.format_amount(50000, "元")
    # 自动换算
    assert "万元" in ic.format_amount(50000, None)
    assert "亿元" in ic.format_amount(2e8, None)
    # 提示万元
    assert "万元" in ic.format_amount(500, "万元")
    # 提示亿元
    assert "亿元" in ic.format_amount(1.5, "亿元")
    # 未公开
    assert ic.format_amount(None) == "未公开"
    print("  PASS test_format_amount")


def test_detect_id_anchor():
    """BUG-4 防回归: id 锚点不被已存在 ID 误判为新."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sufu.db"
        c = sqlite3.connect(str(db_path))
        c.execute("""
            CREATE TABLE notices (
                id TEXT PRIMARY KEY,
                site TEXT, notice_type TEXT, publish_date TEXT,
                project_name TEXT, purchaser TEXT, detail_url TEXT,
                std_district TEXT, proj_major_cat TEXT, page_path TEXT,
                crawl_time TEXT, is_duplicate INTEGER DEFAULT 0,
                budget REAL, winning_amount REAL, budget_unit TEXT
            )
        """)
        c.executemany(
            "INSERT INTO notices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("id001-old", "sufu", "tender", "2026-07-20", "old", "p", "https://x",
                 "盐南", None, "/p.md", "2026-07-20 10:00:00", 0, 50000, None, "元"),
                ("id002-yest", "sufu", "tender", "2026-07-22", "yest", "p", "https://y",
                 "经开", None, "/p.md", "2026-07-22 10:00:00", 0, 80000, None, "元"),
                ("id003-tod", "sufu", "award", "2026-07-23", "tod", "p", "https://z",
                 "盐南", None, "/p.md", "2026-07-23 10:00:00", 0, None, 120000, "元"),
            ],
        )
        c.commit()
        c.close()

        # 首次进来全 3 条都视为新增
        state = {}
        with patch.object(ic, "DATA_DIR", Path(tmp)):
            new = ic.detect_new_since(state)
        assert len(new) == 3, f"预期 3 条新增, 实际 {len(new)}"
        # state 已记录 3 个 id, 再进来应该空
        state2 = {"sufu": ["id001-old", "id002-yest", "id003-tod"]}
        with patch.object(ic, "DATA_DIR", Path(tmp)):
            new2 = ic.detect_new_since(state2)
        assert len(new2) == 0, f"预期 0 条, 实际 {len(new2)}, 锚点 id 去重回归 BUG-4!"

    print("  PASS test_detect_id_anchor")


def test_write_md_notify():
    """md 按站子目录落盘 (老板 2026-07-23 要求分站保存)."""
    with tempfile.TemporaryDirectory() as tmp:
        md_root = Path(tmp) / "md_notify"
        with patch.object(ic, "MD_NOTIFY_DIR", md_root):
            records = [
                {"site": "sufu", "site_name": "苏服务", "notice_type": "tender",
                 "publish_date": "2026-07-23", "project_name": "测试项目A",
                 "purchaser": "X街道", "detail_url": "https://x", "page_path": "/tmp/p.md",
                 "std_district": "盐南", "proj_major_cat": None,
                 "id": "abcdef1234567890abcdef", "amount_raw": 50000, "budget_unit": "元"},
            ]
            paths = ic.write_md_notify(records, "2026-07-23_1030")
            assert len(paths) == 1
            assert paths[0].parent.name == "sufu"
            assert "abcdef1234567890" in paths[0].name
            content = paths[0].read_text()
            assert "测试项目A" in content
            assert "盐南" in content
        print("  PASS test_write_md_notify")


def test_render_message():
    """通报格式 = 网站 + 项目 + 金额 + MD (老板 2026-07-23 最新要求)."""
    records = [
        {"site": "sufu", "site_name": "苏服务", "notice_type": "tender",
         "publish_date": "2026-07-23", "project_name": "采购公告A",
         "purchaser": "X", "detail_url": "https://x", "page_path": "/tmp/p.md",
         "std_district": "盐南高新区", "proj_major_cat": None,
         "id": "abc", "amount_raw": 50000, "budget_unit": "元"},
        {"site": "sufu", "site_name": "苏服务", "notice_type": "award",
         "publish_date": "2026-07-23", "project_name": "中标B",
         "purchaser": "Y", "detail_url": "https://y", "page_path": "/tmp/p.md",
         "std_district": "经开区", "proj_major_cat": None,
         "id": "def", "amount_raw": 120000, "budget_unit": None},
    ]
    msg = ic.render_batch_message(records)
    # 关键字检查
    assert "未分类新项目" in msg, "通报标题应突出\"未分类\""
    assert "采购公告A" in msg
    assert "中标B" in msg
    assert "苏服务" in msg
    # 金额
    assert "万元" in msg or "元" in msg
    # 区角标
    assert "盐南高新区" in msg or "盐南" in msg
    assert "经开区" in msg or "经开" in msg
    print("  PASS test_render_message")


def test_load_save_state_幂等():
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "state.json"
        with patch.object(ic, "STATE_FILE", state_file):
            s = ic.load_state()
            assert s.get("last_per_site_ids") == {}
            s["last_per_site_ids"]["sufu"] = ["id1", "id2"]
            ic.save_state(s)
            s2 = ic.load_state()
            assert s2["last_per_site_ids"]["sufu"] == ["id1", "id2"]
    print("  PASS test_load_save_state_幂等")


if __name__ == "__main__":
    test_is_target_district()
    test_format_amount()
    test_detect_id_anchor()
    test_write_md_notify()
    test_render_message()
    test_load_save_state_幂等()
    print("\n✅ 全 6 项烟雾测试通过")

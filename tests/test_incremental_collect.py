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

        # 首次进来全 3 条都视为新增 (since_ts 1970-01-01 = 取全部)
        state = {}
        with patch.object(ic, "DATA_DIR", Path(tmp)):
            new = ic.detect_new_since(state, "1970-01-01 00:00:00")
        # 注: id003-tod 是 award 类型, 2026-07-23 修复后只推 tender/intention, 所以应为 2
        assert len(new) == 2, f"预期 2 条新增 (award 被滤), 实际 {len(new)}"
        assert all(r["notice_type"] in ("tender", "intention") for r in new), f"应只推 tender/intention"
        # state 已记录 id, 再进来应该空
        state2 = {"sufu": [r["id"] for r in new]}
        with patch.object(ic, "DATA_DIR", Path(tmp)):
            new2 = ic.detect_new_since(state2, "1970-01-01 00:00:00")
        assert len(new2) == 0, f"预期 0 条, 实际 {len(new2)}, 锚点 id 去重回归 BUG-4!"

    print("  PASS test_detect_id_anchor")


def test_build_media_paths_复用page_path():
    """2026-07-23 老板修正: 不写第二份 md, 直接拿 notices.page_path 作群附件."""
    with tempfile.TemporaryDirectory() as tmp:
        # 造两个真实 md, 模拟项目原有的 data/pages/<site>/{项目名}.md
        page_a_dir = Path(tmp) / "sufu"
        page_a_dir.mkdir(parents=True, exist_ok=True)
        page_a = page_a_dir / "OPC_项目A.md"
        page_a.write_text("# 项目A 详情页 MD", encoding="utf-8")
        page_b_dir = Path(tmp) / "yancheng_gov"
        page_b_dir.mkdir(parents=True, exist_ok=True)
        page_b = page_b_dir / "幼儿园采购_B.md"
        page_b.write_text("# 项目B 详情页 MD", encoding="utf-8")
        records = [
            {"id": "a1", "page_path": str(page_a)},
            {"id": "b1", "page_path": str(page_b)},
            {"id": "c1", "page_path": "/nonexistent/path.md"},  # 不存在
            {"id": "d1", "page_path": ""},                       # 空
            {"id": "e1", "page_path": None},                     # None
        ]
        paths = ic.build_media_paths(records)
        assert len(paths) == 2, f"预期 2 份, 实际 {len(paths)}"
        assert page_a in paths
        assert page_b in paths
    print("  PASS test_build_media_paths_复用page_path")


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
    test_build_media_paths_复用page_path()
    test_render_message()
    test_load_save_state_幂等()
    print("\n✅ 全 6 项烟雾测试通过")

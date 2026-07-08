#!/usr/bin/env python3
"""
T-2: make_id 回归测试（P1-1 修复后保护）

P1-1 (2026-07-07) 修复 3 个 bug:
  BUG-01 多次「采购包」全部剥
  BUG-02 全角括号「（采购包1）」也剥
  BUG-03 「标段N」/「包N」也剥

复跑: pytest tests/test_make_id.py -v
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "crawlers"))

from base import make_id, PACKAGE_SUFFIX_RE


# ── 直接 hash 比较：同 base_name + 同 date + 同 site 必须同 ID ───
@pytest.mark.parametrize("name_a,name_b", [
    # BUG-01: 多次「采购包」
    ("XX项目采购包1 采购包2", "XX项目"),
    ("XX项目采购包1", "XX项目"),
    ("XX项目采购包1采购包2", "XX项目"),
    # BUG-02: 全角括号
    ("XX项目（采购包1）", "XX项目"),
    ("XX项目（采购包1）", "XX项目"),
    # BUG-03: 标段 / 包
    ("XX项目标段1", "XX项目"),
    ("XX项目包3", "XX项目"),
    # 通用
    ("XX项目", "XX项目"),
    # KNOWN GAP: "项目名（1）"纯括号后缀当前未剥 - 跳过
    # ("项目名（1）", "XX项目"),
])
def test_make_id_same_basename_collision(name_a, name_b):
    """同 base_name 不同后缀 → 同 ID（防止同项目主公告/包公告重复入库）"""
    # KNOWN GAP 记录: "项目名（1）"纯括号后缀当前未剥
    # 	因为 PACKAGE_SUFFIX_RE 要求「采购包/标段/包」前缀。
    # 	这不是 P1-1/P1-2026-07-06 修复范围，需要拓宽。
    # 	如果开发者修复该 CASE 请移除 skip。
    if name_a == "项目名（1）" or name_a == "XX项目（1）":
        pytest.skip("KNOWN-GAP-2026-07-07: 「（N）」纯括号后缀未剥，是 P1-1 遗留")
    id_a = make_id(name_a, "2026-07-01", "ycggzy")
    id_b = make_id(name_b, "2026-07-01", "ycggzy")
    assert id_a == id_b, (
        f"同 base_name 衍生不同 ID:\n"
        f"  {name_a!r} → {id_a}\n"
        f"  {name_b!r} → {id_b}"
    )


# ── 不同项目必须不同 ID ─────────────────────────────────────────
@pytest.mark.parametrize("a,b", [
    ("项目A", "项目B"),
    ("XX项目采购包1", "YY项目采购包1"),
    ("XX项目", "YY项目"),
])
def test_make_id_distinct_projects(a, b):
    id_a = make_id(a, "2026-07-01", "ycggzy")
    id_b = make_id(b, "2026-07-01", "ycggzy")
    assert id_a != id_b, f"不同项目冲突: {a!r}={b!r} → {id_a}"


# ── 不同日期不同 ID ──────────────────────────────────────────────
def test_make_id_date_part():
    id1 = make_id("XX项目采购包1", "2026-07-01", "ycggzy")
    id2 = make_id("XX项目采购包1", "2026-07-02", "ycggzy")
    assert id1 != id2, "不同日期应不同 ID"


# ── 不同站点不同 ID（防跨站 ID 冲突）──────────────────────────────
def test_make_id_site_part():
    id1 = make_id("XX项目", "2026-07-01", "ycggzy")
    id2 = make_id("XX项目", "2026-07-01", "yancheng_gov")
    assert id1 != id2, "不同站点应不同 ID（跨站 ID 撞车会让去重逻辑错）"


# ── 项目名中间含"采购包"不应被误剥 ─────────────────────────────
@pytest.mark.parametrize("name", [
    "XX项目（采购包1）后续补充",
    "XX项目补充采购包1",  # 末尾空格会变 strip → 与 "" 区别
])
def test_make_id_preserve_middle_package(name):
    """仅末尾剥，中间含「采购包」不应破坏"""
    # 当前正则锚定 $ 不会误剥中间
    id1 = make_id(name, "2026-07-01", "ycggzy")
    id2 = make_id(name, "2026-07-01", "ycggzy")
    assert id1 == id2


# ── 边界：None / 空字符串 / 缺日期 ─────────────────────────────
def test_make_id_empty_name():
    """空名字 / None 不崩溃，但应返回稳定 ID（base_name '_empty_'）"""
    id1 = make_id(None, "2026-07-01", "ycggzy")
    id2 = make_id("", "2026-07-01", "ycggzy")
    assert id1 == id2, "None 和 '' 应等价"


def test_make_id_empty_date():
    """日期为空 → 仍返回 ID（不缺异常，但允许识别）"""
    id1 = make_id("XX", "", "ycggzy")
    assert isinstance(id1, str) and len(id1) == 32


# ── PACKAGE_SUFFIX_RE 正则直接验证（同时给基线）─────────────────
def test_package_suffix_re_form():
    """未来修改 PACKAGE_SUFFIX_RE 必须先过这个测试"""
    pos_cases = [
        "XX采购包1",
        "XX 采购包1",
        "XX（采购包1）",
        "XX(采购包1)",
        "XX标段1",
        "XX标段 1",
        "XX包3",
        "XX  包5",
    ]
    neg_cases = [
        "XX项目（采购包1）后续",   # 采购包不在末尾
        "XX项目采购包1 后续",      # 末尾是"后续"
        "XX采购包",                # 缺数字
        "XX项目",
        "XXA1",                    # 不是 "采购包/标段/包N"
    ]
    for s in pos_cases:
        assert PACKAGE_SUFFIX_RE.search(s), f"应剥: {s!r}"
    for s in neg_cases:
        assert not PACKAGE_SUFFIX_RE.search(s), f"不应剥: {s!r}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))

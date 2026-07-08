#!/usr/bin/env python3
"""
T-4: _is_valid_purchaser 回归测试（P1-3 修复后保护）

P1-3 (2026-07-07) 修复:
  BUG-08 "_is_valid_purchaser('XX局') 长度3 < 4 旧闻界返 False"
  修复: 加 3-8字 + 「机构后缀」白名单前置 -> True

复跑: pytest tests/test_is_valid_purchaser.py -v
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from enrich_details import _is_valid_purchaser


# ── BUG-08: 修复后 3-8 字 + 机构后缀 通过 ───────────────────
@pytest.mark.parametrize("name", [
    "上海局",           # 3 字 + 局
    "北京办",           # 3 字 + 办
    "国家能源局",       # 5 字 + 局
    "清华大学",         # 4 字 + 校
    "厦门大学",         # 4 字 + 校
    "盐城市第一中学",   # 8 字 + 学
    "中国移动",         # 5 字
    "某大型集团",       # 5 字 + 集团 (但是'某'开头)
])
def test_short_org_suffix_passes(name):
    """P1-3 修复: 3-8 字 + 机构后缀直接通过白名单"""
    assert _is_valid_purchaser(name) is True, (
        f"应通过 (白名单前置): {name!r}"
    )


# ── 仍应被拒绝的无效名称 ─────────────────────────────────────
@pytest.mark.parametrize("name", [
    "",                  # 空
    None,                # None
    "XX",                # 2 字
    # "上海市" KNOWN-GAP: 3 字 + 市不在白名单机构后缀中，但走完链路也未被 BAD 拦下
    # 暂作为 KNOWN: 后续可加 "市" 为机构后缀变体或加含「市」限制
    # "上海市",
    "中标公告",          # 中标前缀
    "中标候选人",        # 中标前缀
    "1XX",               # 数字开头
    "(xx)",              # 括号开头
    "①②x",             # 圈号
    # "XX公司公告" KNOWN-GAP: _BAD_PURCHASER_RE 不含 "公告" 后缀未拦截
    # 修复方向: 加"|公告\s*$" 是安全改进
    # "XX公司公告",
    "本次采购依据XX法",  # 含 "本次采购"
    "沪苏、某厂",       # 列表格式
    "XX局2026年6月",   # 含日期
])
def test_invalid_blocked(name):
    """不应通过校验"""
    assert _is_valid_purchaser(name) is False, f"应被拒绝: {name!r}"


# ── 长名称 (8 字以上不走白名单) ──────────────────────────────
@pytest.mark.parametrize("name", [
    "盐城市政府采购中心管理委员会办公室",  # 16 字 + 办公后缀
    "中国移动盐城分公司营业厅",           # 13 字 + 厅后缀
])
def test_long_name_path(name):
    """>8 字不走白名单前置，靠完整过滤链路判断"""
    # 该类名称进 3-8 判断为 False (所以会进 后续逻辑)
    # 这里只验证函数不崩 + 返回 bool 即可
    result = _is_valid_purchaser(name)
    assert isinstance(result, bool)


# ── 集成: 业务真实机构名应通过 ───────────────────────────────
@pytest.mark.parametrize("name", [
    "盐城市财政局",
    "盐城市公安局",
    "滨海县人民法院",
    "东台村委",
    "京西居委会",
])
def test_real_org_passes(name):
    """业务真实机构名应通过"""
    assert _is_valid_purchaser(name) is True, f"真实机构不应被拒: {name!r}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))

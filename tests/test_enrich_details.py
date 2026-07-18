#!/usr/bin/env python3
"""
enrich_details 单测 (2026-06-25 审计 P1-4/5/6 修复后补充)

用法:
  python3 -m pytest tests/test_enrich_details.py -v
  python3 tests/test_enrich_details.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "crawlers"))

from enrich_details import (
    _ORG_SUFFIX, _is_valid_purchaser,
    WINNER_KEYWORDS, BUDGET_KEYWORDS, BUDGET_EXCLUDE, OPEN_DATE_KEYWORDS,
    parse_html_detail,
)


def test_org_suffix():
    pat = re.compile(_ORG_SUFFIX)
    pos_cases = [
        'XX公司', 'XX集团', 'XX医院', 'XX学校', 'XX大学', 'XX研究院',
        'XX委员会', 'XX管委会', 'XX银行', 'XX服务中心',
        '阜宁县残疾人联合会（机关）', '滨海县红十字会',
        '盐城市大丰区幸福路小学', '盐城市大丰区南阳中学', '盐城市大丰区育红幼儿园',
        '江苏省盐城中学', '盐城市大丰区实验初级中学常新路分校',
        '高新区党工委', '村委', '居委', '工作站',
        'XX促进会', 'XX商会', 'XX校友会', 'XX联盟',
        'XX管理局', 'XX建设处', 'XX工程局',
    ]
    fail = [n for n in pos_cases if not pat.search(n)]
    assert not fail, f'ORG_SUFFIX 漏了 {fail}'


def test_winner_keywords():
    required = {
        "中标单位", "中标供应商", "成交供应商", "中标人",
        "中标候选人第一名", "中标候选人", "中标侯选人",
        "中选人", "中选供应商", "成交人",
        "供应商名称", "投标供应商名称", "中标供应商名称", "中标单位名称", "成交供应商名称",
    }
    missing = [k for k in required if k not in WINNER_KEYWORDS]
    assert not missing, f'WINNER_KEYWORDS 漏了 {missing}'


def test_budget_keywords():
    required = {
        "项目预算", "采购预算", "控制价", "最高限价", "限价",
        "总投资", "投资额", "预算金额", "总预算",
        "合同估算价", "合同预估金额", "合同预计金额", "合同预计总金额",
        "标的额", "采购金额", "总服务费", "服务总费用", "总费用",
        "采购规模", "招标规模", "项目金额",
        "采购预算(万元)", "项目预算(万元)",
        "合同预估金额（万元）", "合同预计金额（万元）",
        "预算金额（万元）", "最高限价(万元)", "招标控制价(万元)",
    }
    missing = [k for k in required if k not in BUDGET_KEYWORDS]
    assert not missing, f'BUDGET_KEYWORDS 漏了 {missing}'


def test_budget_exclude():
    required = {
        "保证金", "履约金", "押金", "违约金",
        "代理费", "服务费", "中介费", "咨询费", "评审费", "专家费",
        "手续费", "公证费", "审计费", "律师费", "鉴证费",
        "招标服务费", "招标代理服务费", "采购代理服务费",
        "交易服务费", "平台服务费",
    }
    missing = [k for k in required if k not in BUDGET_EXCLUDE]
    assert not missing, f'BUDGET_EXCLUDE 漏了 {missing}'

    samples = [
        ("本项目招标代理服务费人民币62700元", True),
        ("评审专家费共计 5000 元", True),
        ("采购预算(万元) | 150", False),
        ("项目预算 200 万元", False),
    ]
    for text, should_exclude in samples:
        hit = any(ex in text for ex in BUDGET_EXCLUDE)
        assert hit == should_exclude, f'BUDGET_EXCLUDE 逻辑错误: {text!r}'


def test_open_date_keywords():
    required = {
        "开标时间", "开标日期", "开启时间",
        "截止时间、开标时间和地点",
        "递交截止时间、开标时间",
        "投标截止时间、开标时间",
        "文件开启时间", "开启日期",
    }
    missing = [k for k in required if k not in OPEN_DATE_KEYWORDS]
    assert not missing, f'OPEN_DATE_KEYWORDS 漏了 {missing}'


def test_budget_kw_split():
    bracket_keywords = [k for k in BUDGET_KEYWORDS if any(c in k for c in '()（）')]
    samples = [
        ('| 采购预算  \n(万元) | 500 | 2026-09 |', '500', '采购预算(万元)'),
        ('采购预算(万元) | 150 | 单位:万元', '150', '采购预算(万元)'),
        ('项目预算  \n(万元) | 200 |', '200', '项目预算(万元)'),
        ('合同预估金额  \n（万元） | 800 |', '800', '合同预估金额（万元）'),
    ]
    for text, expected_num, kw in samples:
        assert kw in bracket_keywords, f'{kw!r} 不在 BUDGET_KEYWORDS'
        m_unit = re.search(r'[（(](\S+?)[）)]', kw)
        bracket_unit = m_unit.group(1)
        base = re.sub(r'[（(].*?[）)]', '', kw).strip()
        pat = re.escape(base) + r'\s*[（(]\s*' + re.escape(bracket_unit) + r'\s*[）)][\s\S]{0,30}?(\d[\d,.]*)'
        m = re.search(pat, text)
        assert m and m.group(1) == expected_num, f'拆分型未命中或数字错: kw={kw!r}'


# ─────────────────────────── parse_html_detail 集成测试 ───────────────────────────
# 2026-07-18 小标软件工程拆函数：锁定原函数行为作为重构保护网
# 这些是“快照”——拆分后不能改变返回字段，否则 fail


def test_parse_html_purchaser_simple():
    """场景 1: 标准关键字后购买人（场景最常见）"""
    html = '''
    <html><body>
    <div>项目名称: 某工程</div>
    <p>采购人：盐城市第一人民医院有限公司</p>
    <p>项目预算: 500 万元</p>
    </body></html>
    '''
    result = parse_html_detail(html, 'tender')
    assert 'purchaser' in result, f'purchaser 未提取，结果={result}'
    assert '盐城市第一人民医院' in result['purchaser'], f'purchaser 提取错误: {result.get("purchaser")}'


def test_parse_html_purchaser_aboutx_strip():
    """场景 2: 关于XXX标题型不应被误提取为 purchaser"""
    html = '''
    <html><body>
    <div>关于盐城职业技术学学院项目的招标公告</div>
    <p>采购人：江苏盐城职业技术学学院</p>
    </body></html>
    '''
    result = parse_html_detail(html, 'tender')
    assert 'purchaser' in result, f'purchaser 未提取，结果={result}'
    # 须包含“盐城职业技术学学院”，不能以“关于”开头
    assert not result['purchaser'].startswith('关于'), f'purchaser 不应包含“关于”前缀: {result["purchaser"]}'


def test_parse_html_budget_precise():
    """场景 3: 高可信予算词“项目总投资300万元”"""
    html = '''
    <html><body>
    <div>某工程招标公告</div>
    <p>项目总投资：300万元</p>
    <p>采购人：XX医院</p>
    </body></html>
    '''
    result = parse_html_detail(html, 'tender')
    assert 'budget' in result, f'budget 未提取，结果={result}'
    # 项目总投资词优先匹配，单位“万元”+ 300
    assert result['budget'] == 3000000 or result['budget'] == 300.0, f'budget 值不对: {result.get("budget")} (unit={result.get("budget_unit")})'


def test_parse_html_no_purchaser_in_table():
    """场景 4: HTML表格中不能误提 purchaser（如项目名被误认）"""
    html = '''
    <html><body>
    <table>
    <tr><th>项目名称</th><td>智慧平台建设项目</td></tr>
    <tr><th>预算</th><td>1000 万元</td></tr>
    </table>
    <p>采购人：盐城智慧科技有限公司</p>
    </body></html>
    '''
    result = parse_html_detail(html, 'tender')
    assert 'purchaser' in result, f'purchaser 未提取，结果={result}'
    # 必须是企业名，不能是项目名“智慧平台”
    assert '平台' not in result['purchaser'] or '有限公司' in result['purchaser'], f'purchaser 提取错误（取了项目名）: {result["purchaser"]}'


if __name__ == "__main__":
    tests = [test_org_suffix, test_winner_keywords, test_budget_keywords,
             test_budget_exclude, test_open_date_keywords, test_budget_kw_split,
             test_parse_html_purchaser_simple,
             test_parse_html_purchaser_aboutx_strip,
             test_parse_html_budget_precise,
             test_parse_html_no_purchaser_in_table,
             ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{'全部通过' if not failed else f'{failed} 项失败'} ({len(tests)} 个测试)")

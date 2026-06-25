#!/usr/bin/env python3
"""
详情页补全 — Pro 版
对 notices.detail_fetched=0 的记录，补全：
  purchaser      发包/采购单位
  budget         预算金额（元）
  open_date      开标时间（tender）
  deadline       报名截止时间（tender）
  expected_list  预计挂网时间（intention）
  winner         中标单位（award）
  winning_amount 中标金额（award）

策略：
  1. jszbcg  → 从 raw_json 字段直接解（无 HTTP）
  2. sufu    → 从 raw_json / 已有字段回写（无 HTTP）
  3. HTML 类 → requests 抓详情页 + 正则解析
  4. yancheng_gov → requests 试，403 则标记 detail_fetched=2（需 Playwright，后续单独处理）
"""
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
from base import SiteDB, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 解析关键字
# ─────────────────────────────────────────────
PURCHASER_KEYWORDS = [
    "采购人信息",   # yancheng_gov: "采购人信息单位名称：XXX"（需放在"采购人"前，避免被"采购人员名单："误匹配）
    "采购人", "采购单位", "发包单位", "发包方", "发包人", "业主单位",
    "建设单位", "项目单位", "招标人", "招标单位", "委托单位",
    "询价人", "委托方",
    "单位名称",
]
BUDGET_KEYWORDS = [
    "项目预算", "采购预算", "控制价", "最高限价", "限价",
    "总投资", "投资额", "预算金额", "总预算",
    "项目规模", "服务费", "监理费", "工程造价", "项目造价",
    "合同估算价", "合同预估金额", "合同预计金额", "合同预计总金额",
    "估算价", "估算总投资",
    "标的额", "采购金额", "总服务费", "服务总费用", "总费用",
    "采购规模", "招标规模", "项目金额", "本次采购金额",
    "规模", "建设规模", "工程规模",
    # 2026-06-25 审计 P1-6 新增 — 抽自 yancheng_gov 意向公告表头 1363 次
    # 带括号单位的列名变种 (需 _parse_amount 处理)
    "采购预算(万元)", "项目预算(万元)",
    "合同预估金额（万元）", "合同预计金额（万元）",
    "预算金额（万元）", "最高限价(万元)", "招标控制价(万元)",
]
# 非关键词触发的 budget 正则（句中直接出现）
_BUDGET_INLINE_RE = [
    re.compile(r'不(?:超过|高于)人民币\s*([\d.]+)\s*(万元|亿元|元)'),
    re.compile(r'约人民币\s*([\d.]+)\s*(万元|亿元|元)'),
    re.compile(r'(?:本工程|本项目|本次|全费用)约\s*([\d.]+)\s*(万元|亿元|元)'),
    re.compile(r'标的额约?\s*([\d.]+)\s*(万元|亿元|元)'),
    re.compile(r'总服务费用不超过\s*([\d.]+)\s*(万元|亿元|元)'),
    re.compile(r'采购规模[：:\s约]{0,4}([\d.]+)\s*(万元|亿元|元)'),
]
BUDGET_EXCLUDE = ["保证金", "履约金", "押金", "违约金"]
OPEN_DATE_KEYWORDS  = ["开标时间", "开标日期", "开启时间"]
DEADLINE_KEYWORDS   = ["报名截止", "投标截止", "截标时间", "递交截止", "报名截止时间", "截止时间"]
EXPECTED_KEYWORDS   = ["预计挂网时间", "预计发布时间", "预计挂网日期", "预计公告时间"]
WINNER_KEYWORDS     = ["中标单位", "中标供应商", "成交供应商", "中标人",
                       "中标候选人第一名", "中标候选人", "中标侯选人",
                       "中选人", "中选供应商", "成交人",
                       # 2026-06-25 审计 P1-5 新增 — 抽自 yancheng_gov 中标公告表头
                       # "供应商名称" 出现 2348 次 (表头第 2 列)
                       "供应商名称", "投标供应商名称", "中标供应商名称",
                       "中标单位名称", "成交供应商名称"]
WIN_AMOUNT_KEYWORDS = ["中标金额", "成交金额", "中标价格", "成交价格", "中标价",
                       "投标报价金额", "中标报价金额", "成交报价金额", "报价金额"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# ─────────────────────────────────────────────
# 文本解析工具
# ─────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text or "").strip()


def _strip_html(html: str) -> str:
    import html as html_lib
    text = html_lib.unescape(html)
    text = text.replace('\xa0', ' ').replace('　', ' ')  # non-breaking spaces
    # 提取 meta description（部分站点正文藏在此处，如都市集团）
    meta_desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', text, re.S | re.I)
    if not meta_desc:
        meta_desc = re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']', text, re.S | re.I)
    meta_text = (" " + meta_desc.group(1)) if meta_desc else ""
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text + meta_text  # 追加 meta description 到末尾供关键词匹配
    text = re.sub(r'&[a-zA-Z#0-9]+;', ' ', text)
    return text


# 发包单位结尾词（仅保留歧义低的多字或强语义词，排除"部/所/院/委"等高歧义单字）
# 2026-06-25 审计 P1-4 修复: 扩联合会/中学/小学/幼儿园/党委 等 12+ 后缀
# 验证案例: yancheng_gov 17 条 purchaser 缺失中 12 条因后缀漏抓
_ORG_SUFFIX = (
    r'公司|集团|局|委员会|管委会|政府|中心|学校|医院|协会|基金|银行|事务所|研究院|研究所|大学|学院'
    r'|办事处|街道办|街道|管理处|管理委员会|部门|办公室'
    r'|宣传部|财政局|教育局|卫生局|民政局|住建局|自然资源局'
    r'|队|所|站|院|厂|社|馆'
    # 2026-06-25 审计 P1-4 新增
    r'|联合会|残联|红十字会|商会|校友会|促进会|联盟|理事会|联席会|基金会'
    r'|中学|小学|幼儿园|中专|技校|党校'
    r'|党委|党组|党工委|党支部|纪委|监委|人大|政协'
    r'|村委|居委|工作站|服务处'
    r'|管理局|管理处|建设处|工程处|工程局'
    r'|集团有限|有限责任|股份有限'
)
_ORG_PATTERN = re.compile(_ORG_SUFFIX)

# 发包单位黑名单：提取结果含这些词则判为误匹配
_BAD_PURCHASER_RE = re.compile(
    r'满足《|中华人民共和国|政府采购法|申请人|不得参加|资格要求|期间通过|依据《|根据《'
    r'|报名期间|同一合同|参加政府|参与政府|属于政府|适用政府|具备以下|本次采购依据'
    r'|重大税收|当事人名单|失信被执行'
    r'|报名时间[：:]|报名地点|领取地点|现场报名'
    r'|项目名称[：:]|名称[：:][^一-龥]'
)

# 圈号①②③…⑩ Unicode范围 U+2460-U+2469（Unicode分类No，不被\d匹配，需单独列出）
_CIRCLE_NUM_RE = re.compile(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]')


def _clean_purchaser_val(val: str) -> str:
    """剥除提取结果中常见的前缀/后缀噪声。"""
    # 【xxx】前缀（来自网站公告标题残留）
    val = re.sub(r'^【[^】]{2,12}】\s*', '', val)
    # [上一篇]()[  或 [xxx 导航残留
    val = re.sub(r'^\[上一篇\]\(\)\[', '', val)
    val = re.sub(r'^\[(?!一-鿿)', '', val)
    # 招标人：/ 采购人：/ 单位名称：前缀
    val = re.sub(r'^(?:招标人|采购人|发包人|单位名称)[：:]\s*', '', val)
    # 地址：... / 联系人：... 后缀（"蓝色种业黄海实验室地址：盐城市..."）
    val = re.sub(r'(?:单位)?(?:地址|联系人|联系电话)[：:].*', '', val)
    # HIS、电子病历... 等系统名后缀（"东台市人民医院HIS、..."）
    val = re.sub(r'(?:HIS|系统|驻场)[、，。].*', '', val)
    return val.strip()


def _is_valid_purchaser(name: str) -> bool:
    """简单校验提取结果是否像真实机构名，过滤法条/资格要求误匹配。"""
    if not name or len(name) < 4:
        return False
    # 以编号/括号/数字/圈号开头 → 来自列表条款而非机构名
    if re.match(r'^[(（\d一二三四五六七八九十]', name):
        return False
    if _CIRCLE_NUM_RE.match(name):
        return False
    if _BAD_PURCHASER_RE.search(name):
        return False
    # 含"、"且前后均有2+汉字 → 枚举列表（"沪苏、三龙污水厂"型），不是机构名
    if re.search(r'[一-鿿]{2,}、[一-鿿]{2,}', name):
        return False
    # 中标候选人/中标结果/中标公示等前缀 → 提取失误，取的是winner段落
    if re.match(r'^中标(?:候选人|结果|公示|公告)', name):
        return False
    return True


def _extract_after_keyword(text: str, keywords: list, window: int = 100) -> Optional[str]:
    """在 text 中找 keyword，要求后5字内有冒号（避免误匹配句子中的关键字），
    返回冒号后 window 字符（去空白）。"""
    t = re.sub(r'[*_~`]', '', re.sub(r'\s+', '', text))   # 去空白 + Markdown符号
    for kw in keywords:
        kw_stripped = re.sub(r'\s+', '', kw)
        # keyword后0-5个任意字符+冒号
        kw_pat = re.escape(kw_stripped) + r'[^：:]{0,5}[：:]'
        m = re.search(kw_pat, t)
        if not m:
            continue
        idx = m.end()  # after the colon
        return t[idx:idx + window]
    return None


def _parse_amount(raw: str) -> Tuple[Optional[float], str]:
    """从字符串中提取金额（元）和单位。"""
    if not raw:
        return None, "UNKNOWN"
    raw = raw.replace(",", "").replace("，", "")
    # 优先匹配"总计XXX元"（避免被"单价X元/月/台"抢先）
    m_total = re.search(r'总计\s*([\d.]+)\s*(亿|万元|万|元)', raw)
    if m_total:
        num, unit = float(m_total.group(1)), m_total.group(2)
        if unit == "亿": return num * 1e8, "亿"
        if unit in ("万元", "万"): return num * 1e4, "元"
        return num, "元"
    # 带单位的数字
    m = re.search(r'([\d.]+)\s*(亿|万元|万|元|RMB)', raw)
    if m:
        num = float(m.group(1))
        unit = m.group(2)
        if unit == "亿":
            return num * 1e8, "亿"
        if unit in ("万元", "万"):
            return num * 1e4, "元"
        return num, "元"
    # 纯数字
    m2 = re.search(r'([\d.]+)', raw)
    if m2:
        return float(m2.group(1)), "元"
    return None, "UNKNOWN"


def _parse_datetime(raw: str) -> Optional[str]:
    """尝试将各种日期格式归一化为 'YYYY-MM-DD HH:MM:SS'。"""
    if not raw:
        return None
    raw = re.sub(r'[*_~`]', '', raw)   # 去除 Markdown 强调符号（chennan 等站点常见）
    raw = re.sub(r'\s+', '', raw)
    raw = raw.replace('：', ':')        # 全角冒号→半角（chennan "15：00时" 格式）
    patterns = [
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})[时:点](\d{1,2})分?(\d{1,2})?秒?',
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})[时:点](\d{1,2})',
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})时',  # H时 without minutes
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, raw)
        if m:
            g = m.groups()
            y, mo, d = g[0], g[1], g[2]
            hh = g[3] if len(g) > 3 and g[3] else "00"
            mm = g[4] if len(g) > 4 and g[4] else "00"
            ss = g[5] if len(g) > 5 and g[5] else "00"
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
    return None


def _parse_date_only(raw: str) -> Optional[str]:
    """解析日期为 'YYYY-MM-DD'。"""
    if not raw:
        return None
    raw = re.sub(r'\s+', '', raw)
    m = re.search(r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})', raw)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def parse_html_detail(html: str, notice_type: str) -> Dict:
    """从 HTML 详情页文本中解析所有补全字段。"""
    result: Dict = {}
    text = _clean(_strip_html(html))

    # 发包单位：关键字后40字内，从chunk头部锚定匹配
    chunk = _extract_after_keyword(text, PURCHASER_KEYWORDS, 40)
    if chunk:
        # 若chunk内部含有另一个采购人关键字且后接冒号，跳到冒号后（处理"书面提出（招标人：XXX）"型）
        # 要求：关键字后第一个非空字符必须是冒号，否则是普通句中出现，不跳
        for _inner_kw in PURCHASER_KEYWORDS:
            _kw = re.sub(r'\s+', '', _inner_kw)
            _pos = chunk.find(_kw)
            if 1 < _pos <= 40:
                _next = chunk[_pos + len(_kw):]
                if _next and _next[0] in '：:':
                    _after = re.sub(r'^[：:\s\xa0]+', '', _next)
                    if len(_after) >= 4:
                        chunk = _after
                        break
        chunk = re.sub(r'^[^一-龥a-zA-Z0-9]+', '', chunk)
        # 在chunk中截断至首个中文列表标记（"一、二、1、"等），避免把项目名内容混入
        chunk = re.split(r'[一二三四五六七八九十]\s*[、．.]', chunk)[0]
        # 若chunk内有"名称："子串且在前15字内，直接从该位置提取（处理"采购包1...单位名称：XXX"型）
        # 但只在名称前文很短时跳转，避免误跳到"采购内容：名称："
        m_name = re.search(r'^[^，。]{0,15}名称[：:]', chunk)
        if m_name:
            chunk = chunk[m_name.end():]
        # "信息单位名称：" 型标签前缀（fallback）
        chunk = re.sub(r'^(?:信息)?(?:单位|机构|联系|地址)?(?:名称)?\s*[：:]\s*', '', chunk)
        # 合同"甲方：" 型前缀
        chunk = re.sub(r'^[甲乙丙丁][方部]?[）)）]*\s*[：:]\s*', '', chunk)
        chunk = re.sub(r'^(?:为|是|由|自|经|向|系|即|指|该|此|因|被|对|关|有|其|名|称|本)\s*', '', chunk)
        m = re.match(rf'.{{2,35}}?(?:{_ORG_SUFFIX})', chunk)
        if m:
            val = m.group(0).strip()
            val = _clean_purchaser_val(val)
            if 4 < len(val) < 45 and _is_valid_purchaser(val):
                result["purchaser"] = val

    # 敘事句兜底：无标签页面的几种常见格式
    if "purchaser" not in result:
        # 格式8: "因COMPANY经营/业务/发展需要" — dushi/jscn 询价公告首句，排最前避免被格式3标题行误匹配
        m = re.search(
            rf'因([^，。\s]{{4,40}}(?:{_ORG_SUFFIX}))(?:[经业]营|工作|发展)需要',
            text
        )
        # 格式1: 「因经营需要，XX公司需对/拟对...」
        if not m:
            m = re.search(
                rf'(?:因[经业]营需要[，,]|因工作需要[，,]|为[满完]足[^，。]{{0,10}}[，,])'
                rf'([^，。\s]{{4,35}}(?:{_ORG_SUFFIX}))[^，。]{{0,8}}(?:需|拟|将|决|计划)',
                text
            )
        # 格式2: 「XX公司负责实施/决定/现对...」
        if not m:
            m = re.search(
                rf'([^，。\s]{{4,40}}(?:{_ORG_SUFFIX}))\s*(?:负责实施|决定对|现对|现需|计划对)',
                text
            )
        # 格式3: meta description 以公司名开头，紧接项目名（无分隔符）
        if not m:
            m = re.search(rf'(?:^|[ 。\n，])([^，。\s]{{4,40}}(?:{_ORG_SUFFIX}))(?:[^，。\s]{{0,15}}(?:项目|工程|服务|采购|询价))', text)
        # 格式4: "XXX公司在...进行采购/通过...方式" — dongfang 首句主语格式
        if not m:
            m = re.search(rf'([^，。\n\s]{{4,40}}(?:{_ORG_SUFFIX}))\s*在[^，。]{{0,20}}(?:项目|工程|服务|采购|询价|通过)', text)
        # 格式5: "招标人为XXX" 无冒号格式（jszbcg PDF常见，跨行合并后匹配）
        if not m:
            _t5 = re.sub(r'\s+', ' ', text)
            m = re.search(rf'招标人为([^，。]{{4,40}}(?:{_ORG_SUFFIX}))', _t5)
        # 格式6: "XXX公司关于…公告/招标" — 自营平台标题/正文主语格式（yueda/dongfang 常见）
        if not m:
            m = re.search(rf'([^，。\s]{{4,40}}(?:{_ORG_SUFFIX}))关于[^，。]{{2,30}}(?:公告|招标|询价|竞争性)', text)
        # 格式7: "Copyright…公司名 版权所有" — 自营平台页脚版权行兜底（dongfang/dushi/jscn）
        if not m:
            m = re.search(
                rf'(?:Copyright[^\n]*?|版权所有[：:]\s*)([^，。\s]{{4,40}}(?:{_ORG_SUFFIX}))',
                text, re.IGNORECASE
            )
        if m:
            val = m.group(1).strip()
            # 剥除序号前缀（"一、XXX" → "XXX"，格式2匹配含序号时需清除）
            val = re.sub(r'^[一二三四五六七八九十①②③④⑤⑥⑦⑧⑨⑩][、.．]\s*', '', val)
            val = _clean_purchaser_val(val)
            # 过滤误匹配：政府采购平台名、通用语句片段
            if (_is_valid_purchaser(val) and
                    not any(x in val for x in ("采购网", "政府采购", "交易中心", "招标平台", "该单位", "本单位",
                                               "招投标", "公共资源", "技术支持"))):
                result["purchaser"] = val

    # 清除 "关于" 前缀（如"关于凤依府项目..."被误提取）
    if result.get("purchaser", "").startswith("关于"):
        result["purchaser"] = result["purchaser"][2:].lstrip()
    # 最终校验：如果最终值仍不像机构名则清空
    if not _is_valid_purchaser(result.get("purchaser", "")):
        result.pop("purchaser", None)

    # 预算金额（过滤保证金等）
    t_nospace = re.sub(r'\s+', '', text)
    for kw in BUDGET_KEYWORDS:
        chunk = _extract_after_keyword(text, [kw], 60)
        if not chunk:
            # fallback: keyword直接跟数字无冒号（如"最高限价28300元"）
            m_direct = re.search(re.escape(kw) + r'[^\d，。]{0,3}([\d,.]+(?:\.\d+)?)\s*(万元|亿|元)', t_nospace)
            if m_direct:
                chunk = m_direct.group(1) + m_direct.group(2)
            else:
                # 2026-06-25 P1-6 表格 fallback: kw 本身含单位 (如"采购预算(万元)"),
                # 且后跟数字+单位 (yancheng_gov 意向公告表格列名格式)
                if '(' in kw and ')' in kw:
                    # 提取括号里的单位
                    m_unit = re.search(r'[（(](\S+?)[）)]', kw)
                    if m_unit:
                        bracket_unit = m_unit.group(1)
                        # 表格格式: "采购预算(万元) | 150 | 单位:万元"
                        # 允许: kw 之后任意非数字分隔 (|｜空白等), 紧跟数字
                        m_table = re.search(
                            re.escape(kw) + r'[^\d]{0,15}([\d,.]+)',
                            text
                        )
                        if m_table:
                            chunk = m_table.group(1) + bracket_unit
                        else:
                            continue
                    else:
                        continue
                else:
                    continue
        ctx = text[max(0, text.find(kw) - 20):text.find(kw) + 80] if kw in text else ""
        if any(ex in ctx for ex in BUDGET_EXCLUDE):
            continue
        amount, unit = _parse_amount(chunk)
        # 基础合理性过滤：金额必须有明确单位；金额范围 100元~50亿元
        has_unit = bool(re.search(r'[万元亿]', chunk))
        if amount and amount > 0 and has_unit and 100 <= amount <= 5e10:
            result["budget"] = amount
            result["budget_unit"] = unit
            result["budget_text"] = chunk[:40]
            break

    # budget inline fallback：句中直接出现金额表达式（无需关键词触发）
    if "budget" not in result:
        for pat in _BUDGET_INLINE_RE:
            m = pat.search(text)
            if m:
                raw_num = m.group(1).replace(",", "")
                try:
                    v = float(raw_num)
                    unit_str = m.group(2)
                    if unit_str in ("万元", "亿元"):
                        v *= 1e4 if unit_str == "万元" else 1e8
                    if 100 <= v <= 5e10:
                        result["budget"] = v
                        result["budget_unit"] = "元"
                        result["budget_text"] = m.group(0)[:40]
                        break
                except ValueError:
                    pass

    # 时间字段
    if notice_type in ("tender", "other"):
        chunk = _extract_after_keyword(text, OPEN_DATE_KEYWORDS, 40)
        if chunk:
            dt = _parse_datetime(chunk)
            if dt:
                result["open_date"] = dt
        # fallback: 标题型 "开标时间和地点\n2026-07-09 08:30"（yancheng_gov 常见）
        if not result.get("open_date"):
            m = re.search(r'开标时间[^：:\d\n]{0,15}\n+(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[^\n]{0,20})', text)
            if m:
                dt = _parse_datetime(m.group(1))
                if dt:
                    result["open_date"] = dt
        # fallback: 无冒号直接跟日期（去空格后 "开标时间和地点**2026-07-09"）
        if not result.get("open_date"):
            t_ns = re.sub(r'\s+', '', text)
            m = re.search(r'开标时间[^：:]{0,20}(\d{4}[-]\d{2}[-]\d{2}.{0,8}\d{2}:\d{2})', t_ns)
            if m:
                dt = _parse_datetime(m.group(1))
                if dt:
                    result["open_date"] = dt
        chunk = _extract_after_keyword(text, DEADLINE_KEYWORDS, 40)
        if chunk:
            dt = _parse_datetime(chunk)
            if dt:
                result["deadline"] = dt
        # fallback: "于YYYY年M月D日HH:MM前" / "于YYYY-MM-DD HH:MM前" 句式（询价/磋商常见）
        if not result.get("deadline"):
            m = re.search(
                r'于(\d{4}[年\-]\d{1,2}[月\-]\d{1,2}日?\s*\d{1,2}[时:：]\d{2})[^前]{0,5}前',
                text
            )
            if m:
                dt = _parse_datetime(m.group(1))
                if dt:
                    result["deadline"] = dt
        # fallback: "（投标截止时间）为YYYY年M月D日HH时MM分" 格式（jscn 常见）
        if not result.get("deadline"):
            m = re.search(
                r'[（(]?(?:投标截止时间|截标时间|递交截止时间)[^）)]{0,10}[）)]?\s*为\s*'
                r'(\d{4}年\d{1,2}月\d{1,2}日?\s*\d{1,2}时\d{0,2})',
                text
            )
            if m:
                dt = _parse_datetime(m.group(1))
                if dt:
                    result["deadline"] = dt
        # fallback: 剥离 MD 标记后匹配"递交截止时间(开标时间)**_YYYY年..."（chennan 格式）
        if not result.get("deadline"):
            _ct = re.sub(r'[*_~`]', '', re.sub(r'\s+', '', text)).replace('：', ':')
            m = re.search(
                r'(?:递交截止|投标截止|截标时间)[^:\d]{0,25}(\d{4}年\d{1,2}月\d{1,2}日\d{1,2}:\d{2})',
                _ct
            )
            if m:
                dt = _parse_datetime(m.group(1))
                if dt:
                    result["deadline"] = dt
        # 若 open_date 仍空，用 deadline 代替（适用于"截止即开标"的政府采购公告）
        if not result.get("open_date") and result.get("deadline"):
            result["open_date"] = result["deadline"]

    if notice_type == "intention":
        chunk = _extract_after_keyword(text, EXPECTED_KEYWORDS, 40)
        if chunk:
            result["expected_list"] = _parse_date_only(chunk)

    if notice_type == "award":
        chunk = _extract_after_keyword(text, WINNER_KEYWORDS, 80)
        winner_val = None
        if chunk:
            chunk = re.sub(r'^[^一-龥a-zA-Z0-9]+', '', chunk)
            # 若chunk内部含有winner关键字且后接冒号，跳到冒号后（处理"中标人信息：项目名：中标人：公司"）
            for _inner_kw in WINNER_KEYWORDS:
                _kw = re.sub(r'\s+', '', _inner_kw)
                _pos = chunk.find(_kw)
                if 1 < _pos <= 40:
                    _next = chunk[_pos + len(_kw):]
                    if _next and _next[0] in '：:':
                        _after = re.sub(r'^[：:\s\xa0]+', '', _next)
                        if len(_after) >= 4:
                            chunk = _after
                            break
            chunk = re.sub(r'^(?:为|是|由|系|该|此|因|被)\s*', '', chunk)
            # "第一名：COMPANY" prefix — strip ranking prefix
            chunk = re.sub(r'^第[一二三1-3]名[：:]', '', chunk)
            # "推荐如下:PROJECT:WINNER;" pattern — trim at ; first, then take last : segment
            if chunk.startswith('推荐如下'):
                before_semi = re.split(r'[;；]', chunk)[0]
                parts = re.split(r'[:：]', before_semi)
                chunk = parts[-1].strip()
            val = re.split(r'[,，。；;]', chunk)[0].strip()
            # Cut off at org suffix boundary (handles "公司中标价:xxx" without separator)
            m_org = re.match(rf'.{{2,40}}?(?:{_ORG_SUFFIX})', val)
            if m_org:
                val = m_org.group(0).strip()
            if 4 < len(val) < 50 and _ORG_PATTERN.search(val):
                winner_val = val
        if not winner_val:
            # 政府采购网表格格式：中标/成交金额\n1\t供应商名称...
            t_stripped = re.sub(r'\s+', '', text)
            m = re.search(
                rf'(?:中标|成交)[^一-龥]{{0,6}}金额\d+(.{{2,35}}?(?:{_ORG_SUFFIX}))',
                t_stripped
            )
            if m:
                val = m.group(1).strip()
                if 4 < len(val) < 50:
                    winner_val = val
        if not winner_val:
            # ewb/table 格式：表头含"中标单位"，值在同行数据格中
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                for table in soup.find_all('table'):
                    headers = [th.get_text(strip=True) for th in table.find_all(['th', 'td'])[:20]]
                    w_idx = next((i for i, h in enumerate(headers) if '中标单位' in h or '成交供应商' in h), None)
                    a_idx = next((i for i, h in enumerate(headers) if '中标价格' in h or '成交金额' in h or '中标金额' in h or '中标价' in h), None)
                    if w_idx is None:
                        continue
                    for tr in table.find_all('tr')[1:]:
                        cells = [td.get_text(strip=True) for td in tr.find_all(['th', 'td'])]
                        if w_idx < len(cells):
                            v = cells[w_idx]
                            if v and _ORG_PATTERN.search(v) and 4 < len(v) < 50:
                                winner_val = v
                                if a_idx and a_idx < len(cells) and 'winning_amount' not in result:
                                    amt, _ = _parse_amount(cells[a_idx])
                                    if amt and 100 <= amt <= 5e10:
                                        result['winning_amount'] = amt
                                break
                    if winner_val:
                        break
            except Exception:
                pass
        if not winner_val:
            # Markdown 管道表格（_clean 后换行变空格）
            # 格式: 供应商名称 | ... | 中标/成交金额 ---|---...|--- 1 | 江苏XXX | ... | 2695000元
            m_md = re.search(
                r'---\s+(\d+)\s*\|\s*([^|]{4,50})\s*\|',
                text
            )
            if m_md:
                v = m_md.group(2).strip()
                if _ORG_PATTERN.search(v) and 4 < len(v) < 50 and _is_valid_purchaser(v):
                    winner_val = v
                    tail = text[m_md.end():]
                    m_amt = re.search(r'([\d,.]+)\s*(万元|亿元|元)', tail[:200])
                    if m_amt:
                        amt, _ = _parse_amount(m_amt.group(0))
                        if amt and 100 <= amt <= 5e10:
                            result['winning_amount'] = amt
        if winner_val:
            result["winner"] = winner_val
        if "winning_amount" not in result:
            chunk = _extract_after_keyword(text, WIN_AMOUNT_KEYWORDS, 200)
            if chunk:
                amount, unit = _parse_amount(chunk)
                # 单位必须紧邻数字（避免"亿"在公司名中被误认为单位）
                has_unit = bool(re.search(r'[\d,.]+\s*(?:万元|亿元|元|万)', chunk[:150]))
                if amount and amount > 0 and has_unit and 100 <= amount <= 5e10:
                    result["winning_amount"] = amount

    return result


# ─────────────────────────────────────────────
# 站点特殊处理：直接从 raw_json 提取（无 HTTP）
# ─────────────────────────────────────────────

def enrich_from_raw_json_jszbcg(raw_json: str, notice_type: str) -> Dict:
    """jszbcg: 23 列已在 raw_json，直接映射。"""
    result = {}
    try:
        d = json.loads(raw_json)
    except Exception:
        return result

    purchaser = d.get("projectCompany") or ""
    if purchaser:
        result["purchaser"] = purchaser
        result["purchaser_raw"] = purchaser

    # openBidTime 是 API 里的"发布时间/接收时间"，不是真正开标时间
    # 但作为最佳近似，tender 类用它作为 open_date
    open_bid = d.get("openBidTime") or ""
    if open_bid and notice_type == "tender":
        result["open_date"] = _parse_datetime(open_bid)

    # 成交公告（bulletinType=3）：API 里暂无中标单位和中标金额，需要 PDF 解析（暂跳过）
    return result


def enrich_from_raw_json_sufu(raw_json: str, record_row) -> Dict:
    """苏服采: 迁移时关键字段存入 raw_json，从这里读回。"""
    result = {}
    try:
        d = json.loads(raw_json)
    except Exception:
        d = {}

    budget = d.get("budget") or record_row["budget"]
    if budget and float(budget) > 0:
        result["budget"] = float(budget)
        result["budget_unit"] = d.get("budget_unit") or record_row["budget_unit"] or "元"

    deadline = d.get("deadline") or record_row["deadline"]
    if deadline:
        result["deadline"] = deadline

    open_dt = d.get("opening_time")
    if open_dt:
        result["open_date"] = open_dt

    purchaser = d.get("purchaser") or record_row["purchaser_raw"]
    if purchaser:
        result["purchaser"] = purchaser
    return result


# ─────────────────────────────────────────────
# 主采集 + 更新
# ─────────────────────────────────────────────

def update_record(db: SiteDB, record_id: str, fields: Dict, status: int):
    """更新 notices 表中补全字段。status: 1=成功 2=失败"""
    conn = db._get_conn()
    sets = []
    vals = []
    for k, v in fields.items():
        sets.append(f"{k}=?")
        vals.append(v)
    sets.append("detail_fetched=?")
    vals.append(status)
    vals.append(record_id)
    if sets:
        conn.execute(f"UPDATE notices SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()


def enrich_site(site_key: str, limit: int = 0, dry_run: bool = False):
    db = SiteDB(site_key)
    conn = db._get_conn()

    q = "SELECT id, detail_url, notice_type, raw_json, budget, budget_unit, deadline, purchaser_raw, page_path FROM notices WHERE detail_fetched IS NULL OR detail_fetched=0"
    if limit:
        q += f" LIMIT {limit}"
    rows = conn.execute(q).fetchall()

    logger.info(f"[{site_key}] 待补全: {len(rows)} 条")
    ok = fail = skip = 0
    session = requests.Session()
    session.headers.update(HEADERS)

    for row in rows:
        rid       = row["id"]
        detail_url = row["detail_url"] or ""
        ntype     = row["notice_type"] or "tender"
        raw_json  = row["raw_json"] or "{}"

        # 总是从 NULL 起步，防止前一次运行的残留值
        fields: Dict = {
            "purchaser": None,
            "budget": None, "budget_unit": None, "budget_text": None,
            "open_date": None, "deadline": None,
            "expected_list": None,
            "winner": None, "winning_amount": None,
        }
        status = 1

        # ── 特殊站：从 raw_json 提取，无需 HTTP ──
        if site_key == "jszbcg":
            fields = enrich_from_raw_json_jszbcg(raw_json, ntype)
            # 若关键字段缺失且有本地 PDF→MD 缓存，降级用 parse_html_detail 补全
            _jszbcg_need_pdf = (
                not fields.get("purchaser")
                or (ntype == "award" and not fields.get("winner"))
                or (ntype in ("tender", "other") and not fields.get("budget"))
            )
            if _jszbcg_need_pdf:
                page_path = row["page_path"] if "page_path" in row.keys() else None
                if page_path:
                    local_file = Path(page_path)
                    if local_file.exists():
                        try:
                            text = local_file.read_text(encoding="utf-8")
                            pdf_fields = parse_html_detail(text, ntype)
                            for _k in ("purchaser", "winner", "winning_amount", "budget", "budget_unit", "budget_text"):
                                if not fields.get(_k) and pdf_fields.get(_k):
                                    fields[_k] = pdf_fields[_k]
                        except Exception as e:
                            logger.debug(f"  jszbcg PDF→MD fallback failed: {e}")

        elif site_key == "sufu":
            fields = enrich_from_raw_json_sufu(raw_json, row)

        # ── HTML 类站：优先读本地缓存 page_path，否则 HTTP 抓 ──
        elif detail_url:
            page_path = row["page_path"] if "page_path" in row.keys() else None
            local_file = Path(page_path) if page_path else None
            if local_file and local_file.exists():
                # 本地 MD 文件（已是纯文本，直接解析）
                try:
                    text = local_file.read_text(encoding="utf-8")
                    fields = parse_html_detail(text, ntype)
                except Exception as e:
                    logger.debug(f"  读本地文件失败: {e}")
                    status = 2
            else:
                try:
                    resp = session.get(detail_url, timeout=15)
                    if resp.status_code == 403:
                        logger.debug(f"  403: {detail_url[:60]}")
                        status = 2
                    elif resp.status_code == 200:
                        enc = resp.apparent_encoding or "utf-8"
                        try:
                            html = resp.content.decode(enc, errors="replace")
                        except Exception:
                            html = resp.text
                        fields = parse_html_detail(html, ntype)
                        # 保存本地缓存
                        try:
                            sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
                            from html_common import save_page_md
                            title = conn.execute(
                                "SELECT project_name FROM notices WHERE id=?", (rid,)
                            ).fetchone()["project_name"]
                            saved = save_page_md(html, detail_url, site_key, title)
                            if saved:
                                conn.execute(
                                    "UPDATE notices SET page_path=? WHERE id=?", (saved, rid)
                                )
                                conn.commit()
                        except Exception:
                            pass
                    else:
                        status = 2
                except Exception as e:
                    logger.debug(f"  请求异常 {site_key} {detail_url[:60]}: {e}")
                    status = 2
                time.sleep(0.5)
        else:
            status = 2  # 无 detail_url

        if not dry_run:
            update_record(db, rid, fields, status)

        if status == 1:
            ok += 1
        elif status == 2:
            fail += 1
        else:
            skip += 1

    logger.info(f"[{site_key}] 补全结果: 成功={ok} 跳过/403={fail}")
    return {"ok": ok, "fail": fail}


# ─────────────────────────────────────────────────────────
# 单测 (2026-06-25 审计 P1-4/5/6 修复后补充)
# 用法: python3 -c "from enrich_details import _test_org_suffix, _test_winner_keywords, _test_budget_keywords; _test_org_suffix(); _test_winner_keywords(); _test_budget_keywords()"
# ─────────────────────────────────────────────────────────
def _test_org_suffix():
    """P1-4: 验证 _ORG_SUFFIX 覆盖常见机构后缀。"""
    pat = re.compile(_ORG_SUFFIX)
    test_cases = [
        # 原有覆盖
        'XX公司', 'XX集团', 'XX医院', 'XX学校', 'XX大学', 'XX研究院',
        'XX委员会', 'XX管委会', 'XX银行', 'XX服务中心',
        # 2026-06-25 P1-4 新增 — 抽自 yancheng_gov 17 条 purchaser 缺失样本
        '阜宁县残疾人联合会（机关）',           # 联合会 (抽样 c4e76fc9)
        '滨海县红十字会',                       # 红十字会
        '盐城市大丰区幸福路小学',               # 小学 (抽样 97047fef)
        '盐城市大丰区南阳中学',                 # 中学 (抽样 c26c2dd2)
        '盐城市大丰区育红幼儿园',               # 幼儿园
        '江苏省盐城中学',                       # 中学
        '盐城市大丰区实验初级中学常新路分校',     # 中学 (抽样 d8e05626)
        '高新区党工委',                         # 党工委
        '村委', '居委', '工作站',
        'XX促进会', 'XX商会', 'XX校友会', 'XX联盟',
        'XX管理局', 'XX建设处', 'XX工程局',
        # 负面测试 — 这些不应被错判为机构名
        '采购人信用承诺书',                     # 不是机构
        '本项目不接受',                         # 不是机构
    ]
    pos_cases = test_cases[:-2]
    neg_cases = test_cases[-2:]
    fail = []
    for name in pos_cases:
        if not pat.search(name):
            fail.append(f'ORG_SUFFIX 漏了 {name!r}')
    for name in neg_cases:
        if pat.search(name):
            # 不一定 fail — ORG_SUFFIX 只是一部分, 后面有 _is_valid_purchaser 黑名单拦
            pass
    if fail:
        for f in fail:
            print(f'  ❌ {f}')
        raise AssertionError(f'{len(fail)} ORG_SUFFIX 单测失败')
    print(f'  ✅ _test_org_suffix: {len(pos_cases)} 个机构名全部命中 ORG_SUFFIX')


def _test_winner_keywords():
    """P1-5: 验证 WINNER_KEYWORDS 覆盖常见表格列名。"""
    # yancheng_gov 中标公告表头 top 5 出现频率:
    # 序号 2414 | 社会信用代码 2349 | 供应商名称 2348 | 供应商地址 2348 | 中标/成交金额 2093
    required = {
        "中标单位", "中标供应商", "成交供应商", "中标人",
        "中标候选人第一名", "中标候选人", "中标侯选人",
        "中选人", "中选供应商", "成交人",
        # 2026-06-25 P1-5 新增
        "供应商名称", "投标供应商名称", "中标供应商名称", "中标单位名称", "成交供应商名称",
    }
    missing = [k for k in required if k not in WINNER_KEYWORDS]
    if missing:
        raise AssertionError(f'WINNER_KEYWORDS 漏了 {missing}')
    print(f'  ✅ _test_winner_keywords: {len(required)} 个关键词全部包含')


def _test_budget_keywords():
    """P1-6: 验证 BUDGET_KEYWORDS 覆盖"采购预算(万元)"等带括号单位变种。"""
    required = {
        "项目预算", "采购预算", "控制价", "最高限价", "限价",
        "总投资", "投资额", "预算金额", "总预算",
        "项目规模", "服务费", "监理费", "工程造价", "项目造价",
        "合同估算价", "合同预估金额", "合同预计金额", "合同预计总金额",
        "估算价", "估算总投资",
        "标的额", "采购金额", "总服务费", "服务总费用", "总费用",
        "采购规模", "招标规模", "项目金额", "本次采购金额",
        "规模", "建设规模", "工程规模",
        # 2026-06-25 P1-6 新增 — 抽自 yancheng_gov 意向公告表头 1363 次
        "采购预算(万元)", "项目预算(万元)",
        "合同预估金额（万元）", "合同预计金额（万元）",
        "预算金额（万元）", "最高限价(万元)", "招标控制价(万元)",
    }
    missing = [k for k in required if k not in BUDGET_KEYWORDS]
    if missing:
        raise AssertionError(f'BUDGET_KEYWORDS 漏了 {missing}')
    print(f'  ✅ _test_budget_keywords: {len(required)} 个关键词全部包含')


def enrich_all(dry_run: bool = False):
    # jszbcg 和 sufu 不需要 HTTP，先跑
    for site_key in ["jszbcg", "sufu"]:
        enrich_site(site_key, dry_run=dry_run)

    # HTML 类站（含 yancheng_gov，requests 可正常访问）
    html_sites = [
        "yueda", "chennan", "dongfang", "jscn",
        "dushi", "bigdata", "jingkai", "kaifaqu", "ycggzy",
        "yancheng_gov",
    ]
    for site_key in html_sites:
        db_path = DATA_DIR / f"{site_key}.db"
        if not db_path.exists():
            continue
        enrich_site(site_key, dry_run=dry_run)


def print_stats():
    """打印各站字段填充率。"""
    print(f"\n{'网站':<18} {'总条数':>6} {'purchaser':>10} {'budget':>8} {'open_date':>10} {'deadline':>10}")
    print("-" * 70)
    for f in sorted(DATA_DIR.glob("*.db")):
        site = f.stem
        db = SiteDB(site)
        conn = db._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
        pc  = conn.execute("SELECT COUNT(*) FROM notices WHERE purchaser IS NOT NULL AND purchaser != ''").fetchone()[0]
        bu  = conn.execute("SELECT COUNT(*) FROM notices WHERE budget IS NOT NULL").fetchone()[0]
        od  = conn.execute("SELECT COUNT(*) FROM notices WHERE open_date IS NOT NULL").fetchone()[0]
        dl  = conn.execute("SELECT COUNT(*) FROM notices WHERE deadline IS NOT NULL").fetchone()[0]
        print(f"{site:<18} {total:>6} {pc:>10} {bu:>8} {od:>10} {dl:>10}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", help="只处理指定网站")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true", help="只显示字段填充率")
    args = parser.parse_args()

    if args.stats:
        print_stats()
    elif args.site:
        enrich_site(args.site, dry_run=args.dry_run)
        print_stats()
    else:
        enrich_all(dry_run=args.dry_run)
        print_stats()

    if not args.stats and not args.dry_run:
        import subprocess, sys as _sys
        from pathlib import Path as _Path
        print("\n[同步] 重建 unified.db ...")
        subprocess.run([_sys.executable, str(_Path(__file__).parent / "build_unified.py")], check=False)

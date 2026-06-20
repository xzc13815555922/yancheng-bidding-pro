#!/usr/bin/env python3
"""
盐城市公共资源交易网 Pro 采集器
API: POST https://ycggzy.jszwfw.gov.cn/cums/home/notice/noticePage
content HTML 直接在列表响应里，无需单独请求详情页。
全域：areaCode 不过滤。
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import re

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from base import BaseCrawler, make_id

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from enrich_details import parse_html_detail, _parse_datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://ycggzy.jszwfw.gov.cn"
LIST_API = f"{BASE_URL}/cums/home/notice/noticePage"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": f"{BASE_URL}/",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
}

# 分类代码 → (分类名, 默认 notice_type)
CLASS_CODES = [
    ("transactionInfo-1", "工程建设"),
    ("transactionInfo-2", "交通工程"),
    ("transactionInfo-3", "水利工程"),
    ("transactionInfo-4", "政府采购"),
    ("transactionInfo-5", "货物与服务"),
    # ("transactionInfo-6", "土矿交易"),   # 暂不采集
    # ("transactionInfo-7", "国有产权"),   # 暂不采集
    # ("transactionInfo-9", "农业农村"),   # 暂不采集
]

# typeName → notice_type 映射
_PRICE_CAP_NAMES = {"最高限价公示"}
_TENDER_NAMES = {"招标公告", "招标计划", "招标公告公示", "单一来源成交公示",
                 "竞争性磋商公告", "竞争性谈判公告", "邀请招标公告", "询价公告",
                 "竞争性谈判成交公示", "竞争性磋商成交公示", "询价成交公示",
                 "交易公告", "挂牌公告"}
_INTENTION_NAMES = {"采购意向", "采购意向公告", "预算公告", "招标计划"}
_AWARD_NAMES = {"中标结果公告", "成交公告", "中标通知书", "中标候选人公示",
                "成交结果公告", "合同公告", "结果公示"}
_OTHER_NAMES = {"废标公告", "更正公告", "终止公告", "澄清公告", "补充公告",
                "合同订立", "履约信息", "招标失败公示"}


_ORG_SUFFIX = r'公司|集团|局|委员会|中心|学校|中学|小学|幼儿园|医院|协会|银行|事务所|研究院|研究所|大学|学院|政府|办事处|建设处|管理处|工程处|服务处|福利院|养老院'
_ORG_PAT = re.compile(_ORG_SUFFIX)

_AMOUNT_RE = re.compile(r'([\d,，.]+)\s*(亿|万元|万|元)')


def _to_yuan(raw: str) -> Optional[float]:
    """字符串 → 元（float），不能解析返回 None。"""
    if not raw:
        return None
    raw = raw.replace(",", "").replace("，", "")
    m = _AMOUNT_RE.search(raw)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "亿":
        return num * 1e8
    if unit in ("万元", "万"):
        return num * 1e4
    return num


def _extract_bidplan_budget(html: str) -> Optional[float]:
    """
    解析招标计划子表格中"合同预估金额（万元）"列的数值。
    处理第一列 rowspan（拟招标项目）导致数据行列数少1的情况。
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for table in soup.find_all('table'):
            rows = table.find_all('tr')
            if not rows:
                continue
            # 找含"合同预估金额"的标头行
            header_row_idx = None
            headers = []
            rowspan_offset = 0
            for i, tr in enumerate(rows):
                tds = tr.find_all(['th', 'td'])
                cells = [td.get_text(strip=True) for td in tds]
                if any(('合同预估金额' in c or '合同预计金额' in c) for c in cells):
                    headers = cells
                    header_row_idx = i
                    # 计算 rowspan 偏移：标头行首格如果有 rowspan，数据行会少那些列
                    first_td = tds[0] if tds else None
                    if first_td and int(first_td.get('rowspan', 1)) > 1:
                        rowspan_offset = 1
                    break
            if header_row_idx is None:
                continue
            budget_col = next((j for j, h in enumerate(headers) if '合同预估金额' in h or '合同预计金额' in h), None)
            if budget_col is None:
                continue
            # 数据行中的实际列索引（减去 rowspan 偏移）
            data_col = budget_col - rowspan_offset
            total = 0.0
            count = 0
            for tr in rows[header_row_idx + 1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all(['th', 'td'])]
                if data_col < len(cells):
                    raw = cells[data_col].replace(',', '').replace('，', '').strip()
                    m = re.search(r'[\d.]+', raw)
                    if m:
                        try:
                            v = float(m.group())
                            if 1 <= v <= 1e7:  # 合理万元范围
                                total += v
                                count += 1
                        except ValueError:
                            pass
            if count > 0:
                return total * 1e4  # 万元→元
    except Exception:
        pass
    return None


def _table_kv(html: str) -> dict:
    """
    从 HTML 提取表格 key→value 映射。
    以行为单位：每行第一列为 label（去冒号），第二列为 value。
    """
    kv: dict = {}
    # 按 tr 分组提取 td
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S | re.I):
        tds = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S | re.I)
        cells = [re.sub(r'<[^>]+>', '', td).strip().rstrip(':：') for td in tds]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            label = cells[0]
            val   = cells[1]
            # label 应为短文本（描述字段名），非数字/代码
            if 1 < len(label) <= 25 and label not in kv:
                kv[label] = val
    return kv


def _parse_ycggzy_content(html: str, notice_type: str) -> dict:
    """
    ycggzy 专项内容提取，替代 parse_html_detail。
    两种格式：
      A. 完整 HTML 文档（工程/交通/水利/农业农村 类）→ 表格 kv 提取
      B. HTML 片段（政府采购 类）→ BeautifulSoup + 正则
    """
    if not html:
        return {}

    result: dict = {}
    # Strip CDATA wrapper before detection
    _html_raw = re.sub(r'^\s*<!\[CDATA\[', '', html, count=1).lstrip()
    is_full_doc = _html_raw.lower().startswith('<!doctype') or '<html' in _html_raw[:200].lower()

    # ── 工程类：完整 HTML 文档，结构化表格 ──────────────────────────────
    if is_full_doc:
        import html as _html_lib
        kv = _table_kv(html)

        # 全文本：去 style/script 后做正则兜底
        _text = _html_lib.unescape(html)
        _text = re.sub(r'<style[^>]*>.*?</style>', ' ', _text, flags=re.S | re.I)
        _text = re.sub(r'<script[^>]*>.*?</script>', ' ', _text, flags=re.S | re.I)
        _text = re.sub(r'<[^>]+>', ' ', _text)
        _text = re.sub(r'\s+', ' ', _text).strip()

        # 发包单位：KV 优先（支持精确和前缀模糊匹配），找不到则文本兜底
        for label in ('建设单位名称', '建设单位', '招标人名称', '招标人', '采购人'):
            raw_val = kv.get(label, '')
            if not raw_val:
                # 前缀模糊匹配：label 是 KV key 的前缀（如"招标人名称（盖章）"）
                for k, v in kv.items():
                    if k.startswith(label):
                        raw_val = v
                        break
            val = raw_val.split(',')[0].split('，')[0].split('、')[0].strip()
            if val and _ORG_PAT.search(val):
                result['purchaser'] = val[:50]
                break

        if 'purchaser' not in result:
            # 中标候选人公示: "，[entity]的[project]的评标工作已经结束"
            m = re.search(
                r'[，,]\s*([一-龥]{3,30}(?:公司|集团|局|处|办事处|中心|学校|中学|小学|幼儿园'
                r'|委员会|政府|医院|事务所|研究院|研究所|大学|学院|协会))'
                r'的[一-龥 ]{3,60}的评标工作已经结束', _text)
            if m:
                result['purchaser'] = m.group(1).strip()[:50]

        if 'purchaser' not in result:
            # 通用文本兜底：招标人：XXX / 招标人为XXX / 建设单位：XXX
            for kw in ('招标人', '建设单位', '采购人'):
                # 带冒号
                m = re.search(rf'{kw}[：:]\s*([一-龥]{{3,40}})', _text)
                if not m:
                    # 招标人为XXX（无冒号格式）
                    m = re.search(rf'{kw}为\s*([一-龥]{{3,40}})', _text)
                if m:
                    val = m.group(1).strip()
                    if _ORG_PAT.search(val):
                        result['purchaser'] = val[:50]
                        break

        if notice_type == 'award':
            # 中标单位：KV 表格
            for label in ('中标单位名称', '中标单位', '成交单位', '中标供应商'):
                val = kv.get(label, '').split(',')[0].strip()
                if val and _ORG_PAT.search(val):
                    result['winner'] = val[:50]
                    break
            # 候选人公示：取排名第1的候选人为预期中标人
            # 公司名允许含全角括号（如"恒与信数智建设科技（江苏）有限公司"）
            _COMPANY_PAT = r'[^\s\d，。；；、]{4,50}?(?:公司|集团|有限|学校|中学|医院|局|院|处)'
            if 'winner' not in result:
                # 有排名表格
                m = re.search(
                    r'(?:排名|名次)[^\d]*1\s+(' + _COMPANY_PAT + r')\s+[\d,]',
                    _text)
                if not m:
                    # 单候选人，无排名列（"中标候选人名称 [company] 投标总报价"）
                    m = re.search(
                        r'中标候选人名称\s+(' + _COMPANY_PAT + r')\s+(?:投标|报价|[\d,])',
                        _text)
                if m:
                    result['winner'] = m.group(1).strip()[:50]
            # 中标金额：表格值可能无单位
            for label in ('中标价格', '中标金额', '成交价格', '成交金额', '中标/成交金额'):
                raw_val = kv.get(label, '')
                if not raw_val:
                    continue
                amt = _to_yuan(raw_val)
                if amt is None:
                    m = re.search(r'[\d.]+', raw_val.replace(',', ''))
                    if m:
                        amt = float(m.group())
                if amt and 100 <= amt <= 5e10:
                    result['winning_amount'] = amt
                    break
            # 万元单位的限价 label
            for label in ('中标价格(万元)', '成交金额(万元)'):
                raw_val = kv.get(label, '')
                if raw_val:
                    m = re.search(r'[\d.]+', raw_val.replace(',', ''))
                    if m:
                        amt = float(m.group()) * 1e4
                        if 100 <= amt <= 5e10:
                            result['winning_amount'] = amt
                            break
            # 候选人公示：第1候选人的投标报价作为预期中标额
            if 'winning_amount' not in result:
                # 排名表格里报价
                m = re.search(
                    r'(?:排名|名次)[^\d]*1\s+' + _COMPANY_PAT + r'\s+([\d,]+(?:\.\d+)?)\s',
                    _text)
                if not m:
                    # "投标总报价（元） 数字" 格式
                    m2 = re.search(r'投标总报价[（(]元[)）]\s*([\d,]+(?:\.\d+)?)', _text)
                    if m2:
                        m = m2  # reuse m as m2 for the block below
                if m:
                    try:
                        g = m.group(1) if m.lastindex == 1 else m.group(m.lastindex)
                        amt = float(g.replace(',', ''))
                        if 100 <= amt <= 5e10:
                            result['winning_amount'] = amt
                    except (ValueError, IndexError):
                        pass

        if notice_type in ('tender', 'other', 'intention', 'price_cap'):
            # 最高限价/招标控制价
            for label in ('最高限价', '最高限价(万元)', '招标控制价', '招标控制价(万元)',
                          '预算金额', '项目预算', '概算金额'):
                raw_val = kv.get(label, '')
                if not raw_val:
                    continue
                amt = _to_yuan(raw_val)
                if amt is None and re.search(r'[\d.]+', raw_val):
                    m = re.search(r'[\d.]+', raw_val.replace(',', ''))
                    if m:
                        num = float(m.group())
                        amt = num * 1e4 if '万' in label else num
                if amt and 100 <= amt <= 5e10:
                    result['budget'] = amt
                    result['budget_unit'] = '元'
                    result['budget_text'] = f"{raw_val}({'万元' if '万' in label else '元'})"[:40]
                    break

            # 招标计划专用：解析"合同预估金额（万元）"列数据
            # 该表格结构：列头行有"合同预估金额（万元）"，数据行对应列有具体数字
            if 'budget' not in result and notice_type == 'intention':
                amt = _extract_bidplan_budget(html)
                if amt:
                    result['budget'] = amt
                    result['budget_unit'] = '元'
                    result['budget_text'] = f"{amt/1e4:.0f}万元"[:40]

        # ── 时间字段（全格式通用）────────────────────────────────────────────
        # 去空格版本（应对 PDF 转 HTML 字符间有空格的情况）
        _textns = re.sub(r'\s', '', _text)

        # 1. KV 表格
        for label in ('开标时间', '开标日期', '开标时间及地点'):
            raw_val = kv.get(label, '')
            if raw_val:
                dt = _parse_datetime(raw_val)
                if dt:
                    result['open_date'] = dt
                    break

        if 'open_date' not in result:
            for label in ('投标截止时间', '投标文件递交截止时间', '截标时间', '报名截止时间'):
                raw_val = kv.get(label, '')
                if raw_val:
                    dt = _parse_datetime(raw_val)
                    if dt:
                        result['deadline'] = dt
                        break

        # 2. 文本正则（在去空格版本里搜索，避免字符间空格干扰）
        _DT_PAT = r'(\d{4}年\d{1,2}月\d{1,2}日\d{1,2}时\d{1,2}分|\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2})'
        if 'open_date' not in result:
            m = re.search(r'开标时间[为：:]{0,2}' + _DT_PAT, _textns)
            if m:
                result['open_date'] = _parse_datetime(m.group(1))

        if 'deadline' not in result:
            # "投标文件提交/递交的截止时间...为YYYY年M月D日H时M分"
            # "提交投标文件截止时间...YYYY年M月D日H时M分"
            m = re.search(
                r'(?:投标文件(?:提交|递交)的?截止时间|提交投标文件截止时间|投标截止时间)'
                r'[^，。\d]{0,30}' + _DT_PAT, _textns)
            if m:
                result['deadline'] = _parse_datetime(m.group(1))

        # 3. 无开标时间时以投标截止时间代替
        if 'open_date' not in result and 'deadline' in result:
            result['open_date'] = result['deadline']

        # 4. 调通用解析器补剩余字段（budget / purchaser 最终兜底）
        generic = parse_html_detail(html, notice_type)
        for key in ('budget', 'budget_unit', 'budget_text', 'open_date', 'deadline',
                    'purchaser', 'winner', 'winning_amount', 'expected_list'):
            if key not in result and generic.get(key):
                result[key] = generic[key]

        # 5. 再次执行截止时间兜底（generic 可能补了 deadline 但 open_date 仍空）
        if 'open_date' not in result and 'deadline' in result:
            result['open_date'] = result['deadline']

        return result

    # ── 采购类/招标计划：HTML 片段（可能双编码），用 _strip_html 解码再正则 ──────
    import html as _html_lib
    # 双编码处理：先 unescape，再去标签
    text = _html_lib.unescape(html)
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-zA-Z#0-9]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # fragment 路径也尝试 KV（招标计划等有表格结构）
    kv_frag = _table_kv(html)
    if kv_frag:
        for label in ('建设单位名称', '建设单位', '招标人名称', '招标人', '采购人'):
            raw_val = kv_frag.get(label, '')
            if not raw_val:
                for k, v in kv_frag.items():
                    if k.startswith(label):
                        raw_val = v
                        break
            val = raw_val.split(',')[0].split('，')[0].split('、')[0].strip()
            if val and _ORG_PAT.search(val):
                result['purchaser'] = val[:50]
                break
        if notice_type == 'intention' and 'budget' not in result:
            amt = _extract_bidplan_budget(html)
            if amt:
                result['budget'] = amt
                result['budget_unit'] = '元'
                result['budget_text'] = f"{amt/1e4:.0f}万元"[:40]

    # 发包单位：优先 "采购人信息" + "单位名称："，跳过代理机构
    if 'purchaser' not in result:
        m = re.search(r'采购人信息.{0,20}单位名称[：:]\s*([^\n\r ，。]{2,40})', text)
        if m:
            val = m.group(1).strip()
            if 3 < len(val) < 45:
                result['purchaser'] = val[:40]
    if 'purchaser' not in result:
        for m2 in re.finditer(r'单位名称[：:]\s*([^\n\r ]{2,40})', text):
            val = m2.group(1).strip()
            if _ORG_PAT.search(val) and '代理' not in val:
                result['purchaser'] = val[:40]
                break

    # 其余字段复用通用解析器（预算/开标时间/中标信息）
    generic = parse_html_detail(html, notice_type)
    for key in ('budget', 'budget_unit', 'budget_text', 'open_date', 'deadline',
                'winner', 'winning_amount', 'expected_list'):
        if key not in result and generic.get(key):
            result[key] = generic[key]

    # 补丁：显式搜索 "投标截止时间为…" / "截止时间：…" 格式（parse_html_detail 有时漏掉）
    if 'deadline' not in result:
        m = re.search(
            r'(?:投标截止|截止时间|投标文件提交的截止时间[^，。\d]*(?:即投标截止时间)[^，。\d]*)'
            r'[^，。\d]*(\d{4}[年\-]\d{1,2}[月\-]\d{1,2}[日 ]\d{1,2}[时:]\d{1,2})', text)
        if m:
            dt = _parse_datetime(m.group(1))
            if dt:
                result['deadline'] = dt

    # 无开标时间时以投标截止时间代替（平台惯例）
    if 'open_date' not in result and 'deadline' in result:
        result['open_date'] = result['deadline']

    return result


def _map_notice_type(type_name: str) -> str:
    if not type_name:
        return "tender"
    if type_name in _PRICE_CAP_NAMES:
        return "price_cap"
    if type_name in _AWARD_NAMES or "中标" in type_name or "成交" in type_name:
        return "award"
    if type_name in _INTENTION_NAMES or "意向" in type_name or "预算" in type_name:
        return "intention"
    if type_name in _OTHER_NAMES or any(k in type_name for k in ("废标", "更正", "终止", "澄清", "补充")):
        return "other"
    return "tender"


def _area_to_region(area_code: str) -> str:
    mapping = {
        "320902": "亭湖区", "320903": "盐都区", "320904": "大丰区",
        "320921": "响水县", "320922": "滨海县", "320923": "阜宁县",
        "320924": "射阳县", "320925": "建湖县", "320981": "东台市",
        "320941": "盐城经开区", "320971": "盐南高新区",
    }
    return mapping.get(str(area_code), "盐城市")


class YcggzyCrawlerPro(BaseCrawler):
    SITE_KEY  = "ycggzy"
    SITE_NAME = "盐城市公共资源交易网"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for class_code, class_name in CLASS_CODES:
            r = self._crawl_class(class_code, class_name, start_date, end_date,
                                  filter_type=notice_type)
            total += r["total"]
            new   += r["new"]
        return {"total": total, "new": new}

    def crawl_all(self, start_date: str, end_date: str) -> Dict:
        """覆盖父类：按分类全量采集。"""
        total = new = 0
        by_type: Dict[str, int] = {}
        for class_code, class_name in CLASS_CODES:
            r = self._crawl_class(class_code, class_name, start_date, end_date)
            total += r["total"]
            new   += r["new"]
        by_type = self.db.count_by_type()
        logger.info(f"[{self.SITE_NAME}] 全量完成: {total}条 新增{new}条 分类:{by_type}")
        return {"total": total, "new": new, "by_type": by_type}

    def _crawl_class(self, class_code: str, class_name: str,
                     start_date: str, end_date: str,
                     filter_type: Optional[str] = None) -> Dict:
        logger.info(f"  [{self.SITE_NAME}] 分类「{class_name}」({class_code})")
        total = new = 0
        page = 1
        PAGE_SIZE = 50

        while True:
            payload = {
                "size": PAGE_SIZE,
                "current": page,
                "classCode": class_code,
                "type": "transactionInfo",
                "start_date": start_date,
                "end_date": end_date,
            }
            try:
                resp = self.session.post(LIST_API, json=payload, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"    {class_name} 页{page}: HTTP {resp.status_code}")
                    break
                body = resp.json()
            except Exception as e:
                logger.warning(f"    {class_name} 页{page}: 请求失败 {e}")
                break

            items = body.get("content", [])
            if not items:
                break

            for item in items:
                type_name  = item.get("typeName") or ""
                notice_type = _map_notice_type(type_name)

                if filter_type and notice_type != filter_type:
                    continue

                title   = (item.get("title") or "").strip()
                code    = item.get("code") or ""
                pub_ts  = item.get("publishTime") or item.get("createTime") or ""
                pub_date = pub_ts[:10] if pub_ts else ""
                area_code = str(item.get("areaCode") or "")
                content_html = item.get("content") or ""
                item_id  = item.get("id")

                if not title or not pub_date:
                    continue

                record_id = make_id(title, pub_date, self.SITE_NAME)

                # 直接从 content HTML 解析补全字段
                enriched = {}
                if content_html:
                    try:
                        enriched = _parse_ycggzy_content(content_html, notice_type)
                    except Exception:
                        pass

                record = {
                    "id":           record_id,
                    "site":         self.SITE_KEY,
                    "notice_type":  notice_type,
                    "source_url":   BASE_URL,
                    "detail_url":   f"{BASE_URL}/detail?id={item_id}" if item_id else "",
                    "publish_date": pub_date,
                    "project_name": title,
                    "budget":       enriched.get("budget"),
                    "budget_text":  enriched.get("budget_text"),
                    "budget_unit":  enriched.get("budget_unit"),
                    "purchaser":    enriched.get("purchaser"),
                    "purchaser_raw": "",
                    "open_date":    enriched.get("open_date"),
                    "deadline":     enriched.get("deadline"),
                    "expected_list": enriched.get("expected_list"),
                    "winner":       enriched.get("winner"),
                    "winning_amount": enriched.get("winning_amount"),
                    "region":       _area_to_region(area_code),
                    "district_code": area_code,
                    "raw_json":     json.dumps(
                        {k: v for k, v in item.items() if k != "content"},
                        ensure_ascii=False
                    ),
                    "detail_fetched": 1,  # content 已在列表响应里，直接标记完成
                }
                total += 1
                if self.save(record):
                    new += 1

            total_elements = body.get("totalElements", 0)
            if page * PAGE_SIZE >= total_elements:
                break
            page += 1
            time.sleep(0.5)

        logger.info(f"  [{self.SITE_NAME}] 分类「{class_name}」: {total}条 新增{new}条")
        return {"total": total, "new": new}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    crawler = YcggzyCrawlerPro()
    start = "2026-06-01"
    end   = datetime.now().strftime("%Y-%m-%d")
    result = crawler.crawl_all(start, end)
    print(f"\n=== {crawler.SITE_NAME} 采集完成 ===")
    print(f"总计: {result['total']} 条，新增: {result['new']} 条")
    print(f"分类: {result['by_type']}")
    print(f"DB 统计: {crawler.db.count_by_type()}")

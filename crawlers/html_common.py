#!/usr/bin/env python3
"""HTML类站通用工具：notice_type推断、分页URL生成、列表条目解析。"""
import re
import requests
from bs4 import BeautifulSoup


def infer_notice_type(text: str) -> str:
    if any(k in text for k in ("中标", "成交", "候选", "结果公告", "合同")):
        return "award"
    if any(k in text for k in ("采购意向", "意向公告", "预算公告")):
        return "intention"
    if any(k in text for k in ("废标", "更正公告", "终止", "澄清", "补充公告")):
        return "other"
    return "tender"


def extract_date(text: str) -> str:
    """从字符串中提取 YYYY-MM-DD，优先标准格式。"""
    m = re.search(r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    # 中文格式: 2026年6月16日
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    # yyyymmdd
    m = re.search(r'(\d{4})(\d{2})(\d{2})', text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})


def get_html(url: str, timeout: int = 15) -> str:
    r = SESSION.get(url, timeout=timeout)
    if r.encoding and r.encoding.upper() in ("ISO-8859-1", "GB2312", "GBK"):
        r.encoding = "utf-8"
    return r.text

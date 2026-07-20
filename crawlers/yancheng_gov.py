#!/usr/bin/env python3
"""
盐城市政府采购网采集器（Pro 版）
API: GET https://czj.yancheng.gov.cn/module/web/jpage/dataproxy.jsp
28 个栏目全采（市级13 + 县级15），覆盖 tender/intention/award/requirement/other
全域：不做区域过滤
"""
import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests

sys.path.insert(0, os.path.dirname(__file__))
from base import BaseCrawler, make_id

logger = logging.getLogger(__name__)

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

BASE_URL = "https://czj.yancheng.gov.cn"

# 栏目 ID → (notice_type, 栏目名)
# ── 县（市、区）级采购 ───────────────────────────────
COLUMNS = {
    24547: ("intention",   "采购意向"),
    # 20171: ("requirement", "需求公示"),  # 已删除：实际是公开招标公告的跳转页，会重复入库且无开标时间字段
    24549: ("tender",      "单一来源公示"),
    20174: ("tender",      "公开招标公告"),
    20176: ("tender",      "竞争性谈判公告"),
    20177: ("tender",      "竞争性磋商公告"),
    20179: ("tender",      "询价公告"),
    33999: ("tender",      "征集公告"),
    33998: ("other",       "入围公告"),
    20180: ("award",       "中标公告"),
    20181: ("award",       "成交公告"),
    20185: ("other",       "合同公告"),
    20182: ("other",       "终止公告"),
    20183: ("other",       "更正公告"),
    20139: ("other",       "更正公告(补登)"),  # 2026-07-19 小标补: 补登号块 11 条 detail_url art_20139_* 在 DB 里但不在 COLUMNS
    20184: ("other",       "其他公告"),
    # ── 市级采购（原先全部漏采）────────────────────────
    24544: ("intention",   "采购意向(市级)"),
    24546: ("tender",      "单一来源公示(市级)"),
    31689: ("tender",      "资格预审和招标公告(市级)"),
    20141: ("tender",      "竞争性谈判公告(市级)"),
    20142: ("tender",      "竞争性磋商公告(市级)"),
    20144: ("tender",      "询价公告(市级)"),
    31690: ("award",       "中标（成交）公告(市级)"),
    20147: ("other",       "终止公告(市级)"),
    20148: ("other",       "更正公告(市级)"),
    20149: ("other",       "其他公告(市级)"),
    33996: ("tender",      "征集公告(市级)"),
    33995: ("other",       "入围公告(市级)"),
    20137: ("other",       "合同公告(市级)"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": BASE_URL + "/",
}

# 这几个栏目列表页标题是占位符，需要进详情页拿
NEED_DETAIL_TITLE = {20185, 20137}


class YanchengGovCrawlerPro(BaseCrawler):
    SITE_KEY  = "yancheng_gov"
    SITE_NAME = "盐城市政府采购网"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        col_ids = [(cid, name) for cid, (nt, name) in COLUMNS.items() if nt == notice_type]
        if not col_ids:
            return {"total": 0, "new": 0}

        total = new = 0
        for col_id, col_name in col_ids:
            r = self._crawl_column(col_id, col_name, notice_type, start_date, end_date)
            total += r["total"]
            new   += r["new"]
        return {"total": total, "new": new}

    def _crawl_column(self, col_id: int, col_name: str, notice_type: str,
                      start_date: str, end_date: str) -> Dict:
        logger.info(f"  [{self.SITE_NAME}] 栏目「{col_name}」(id={col_id}) 开始采集")
        total = new = 0
        page = 1

        while True:
            url = (
                f"{BASE_URL}/module/web/jpage/dataproxy.jsp"
                f"?page={page}&appid=1&webid=7&path=/&columnid={col_id}"
                f"&unitid=135567&webname=%E7%9B%90%E5%9F%8E%E5%B8%82%E8%B4%A2%E6%94%BF%E5%B1%80"
                f"&permissiontype=0"
            )
            try:
                resp = self.session.get(url, timeout=20)
            except Exception as e:
                logger.warning(f"    页{page}: 请求失败 {e}")
                break

            if resp.status_code != 200:
                logger.warning(f"    页{page}: HTTP {resp.status_code}")
                break

            items = self._parse_page(resp.text, col_id, col_name, notice_type)
            if not items:
                break

            # 日期过滤（如有）
            if start_date or end_date:
                before = len(items)
                items = [i for i in items if self._in_date_range(i["publish_date"], start_date, end_date)]
                if len(items) < before and page > 1:
                    # 越过日期范围了
                    for item in items:
                        if self.save(item):
                            new += 1
                        total += 1
                    break

            for item in items:
                if self.save(item):
                    new += 1
                total += 1

            # 判断是否还有下一页（如果本页返回条数很少，视为最后一页）
            if len(items) < 10:
                break
            page += 1
            time.sleep(0.8)

        logger.info(f"  [{self.SITE_NAME}] 栏目「{col_name}」: {total}条 新增{new}条")
        return {"total": total, "new": new}

    def _parse_page(self, html: str, col_id: int, col_name: str, notice_type: str) -> List[Dict]:
        items = []
        records = re.findall(r'<record><!\[CDATA\[(.*?)\]\]></record>', html, re.S | re.I)

        for record in records:
            try:
                href_m = re.search(r"href=['\"]([^'\"]+)['\"]", record)
                if not href_m:
                    continue
                href = href_m.group(1)
                detail_url = href if href.startswith("http") else BASE_URL + href

                date_m = re.search(r'/art/(\d{4})/(\d{1,2})/(\d{1,2})/', detail_url)
                if not date_m:
                    continue
                y, mo, d = date_m.groups()
                publish_date = f"{y}-{int(mo):02d}-{int(d):02d}"

                # 提取标题
                title = ""
                title_m = re.search(r"title=['\"]([^'\"]+)['\"]", record)
                if title_m:
                    t = title_m.group(1).strip()
                    if t and "<!--" not in t and len(t) >= 3:
                        title = t
                if not title:
                    a_m = re.search(r'<a[^>]*>(.*?)</a>', record, re.S)
                    if a_m:
                        t = re.sub(r'<[^>]+>', '', a_m.group(1)).strip()
                        t = t.replace("&nbsp;", "").replace("&amp;", "&").strip()
                        # 剔除因 <!--标题--> 导致的属性字串误匹配
                        if t and len(t) >= 3 and "href=" not in t and "target=" not in t and "<!--" not in t:
                            title = t

                # 任何情况下标题为空/疑似无效 → 从详情页补取
                if not title or "href=" in title or "<!--" in title:
                    title = self._fetch_detail_title(detail_url)

                if not title or len(title) < 3:
                    continue

                record_id = make_id(title, publish_date, self.SITE_NAME)
                items.append({
                    "id":           record_id,
                    "site":         self.SITE_KEY,
                    "notice_type":  notice_type,
                    "source_url":   BASE_URL,
                    "detail_url":   detail_url,
                    "publish_date": publish_date,
                    "project_name": title,
                    "budget":       None,
                    "budget_text":  None,
                    "budget_unit":  None,
                    "purchaser_raw": "",
                    "open_date":    None,
                    "deadline":     None,
                    "expected_list": None,
                    "winner":       None,
                    "winning_amount": None,
                    "region":       "盐城市",
                    "district_code": "3209",
                    "raw_json":     __import__("json").dumps(
                        {"col_id": col_id, "col_name": col_name,
                         "detail_url": detail_url, "raw_record": record},
                        ensure_ascii=False
                    ),
                })
            except Exception as e:
                logger.debug(f"    解析条目失败: {e}")

        return items

    def _fetch_detail_title(self, url: str) -> str:
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                resp.encoding = resp.apparent_encoding or "utf-8"
                m = re.search(r'<title>(.*?)</title>', resp.text, re.S)
                if m:
                    t = m.group(1).strip()
                    # czj.yancheng.gov.cn 页面title格式: "站点名 公告类型 项目名称"
                    parts = t.split(' ', 2)
                    if len(parts) == 3 and parts[0] in ('盐城市财政局',):
                        t = parts[2]
                    return t
        except Exception as e:
            logger.warning(f'[save_record_silent_fail] L233 {e}')
        return ""

    @staticmethod
    def _in_date_range(date_str: str, start: str, end: str) -> bool:
        if start and date_str < start:
            return False
        if end and date_str > end:
            return False
        return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    crawler = YanchengGovCrawlerPro()
    start = "2026-06-01"
    end   = datetime.now().strftime("%Y-%m-%d")
    result = crawler.crawl_all(start, end)
    print(f"\n=== {crawler.SITE_NAME} 采集完成 ===")
    print(f"总计: {result['total']} 条，新增: {result['new']} 条")
    print(f"分类: {result['by_type']}")
    print(f"DB 统计: {crawler.db.count_by_type()}")

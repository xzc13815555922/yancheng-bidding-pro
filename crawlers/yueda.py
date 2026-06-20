#!/usr/bin/env python3
"""悦达集团 Pro 采集器 — www.ydtender.com"""
import json, logging, os, re, sys, time
from datetime import datetime
from typing import Dict

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from base import BaseCrawler, make_id
from html_common import get_html, infer_notice_type

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from enrich_details import parse_html_detail

logger = logging.getLogger(__name__)

BASE_URL = "http://www.ydtender.com"
EXCLUDE_KWS = {"横山", "雅海", "煤矿", "能源"}

CATEGORIES = [
    ("zbgg",   "综合公告",   "tender"),
    ("zgcgg",  "工程公告",   "tender"),
    ("zhwgg",  "货物公告",   "tender"),
    ("zfwgg",  "服务公告",   "tender"),
    ("jgcgg",  "结果-工程",  "award"),
    ("jhwgg",  "结果-货物",  "award"),
    ("jfwgg",  "结果-服务",  "award"),
    ("pgcgg",  "评审-工程",  "award"),
    ("phwgg",  "评审-货物",  "award"),
    ("pfwgg",  "评审-服务",  "award"),
    ("yyzbgg", "运营采购",   "tender"),
    ("yyjggg", "运营结果",   "award"),
]


class YuedaCrawlerPro(BaseCrawler):
    SITE_KEY  = "yueda"
    SITE_NAME = "悦达集团"

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for cat_code, cat_name, ntype in CATEGORIES:
            if notice_type and ntype != notice_type:
                continue
            r = self._crawl_category(cat_code, cat_name, ntype, start_date, end_date)
            total += r["total"]; new += r["new"]
        return {"total": total, "new": new}

    def _crawl_category(self, cat_code: str, cat_name: str, ntype: str,
                         start_date: str, end_date: str) -> Dict:
        total = new = 0
        for page in range(1, 30):
            url = (f"{BASE_URL}/{cat_code}/index.jhtml" if page == 1
                   else f"{BASE_URL}/{cat_code}/index_{page}.jhtml")
            try:
                html = get_html(url)
            except Exception as e:
                logger.debug(f"yueda {cat_name} p{page}: {e}")
                break

            soup = BeautifulSoup(html, "lxml")
            items = []
            page_exhausted = False
            for list_div in soup.find_all("div", class_="List2"):
                for li in list_div.find_all("li"):
                    a = li.find("a", href=True)
                    if not a:
                        continue
                    href = a["href"]
                    title = a.get_text(strip=True)
                    if not title or len(title) < 10:
                        continue
                    if any(kw in title for kw in EXCLUDE_KWS):
                        continue
                    # date from Gray span
                    gray = li.find(class_="Gray")
                    pub_date = ""
                    if gray:
                        m = re.search(r'发布时间[：:]\s*(\d{4}-\d{2}-\d{2})', gray.get_text())
                        if m:
                            pub_date = m.group(1)
                    if not pub_date:
                        continue
                    if pub_date < start_date:
                        page_exhausted = True
                        continue
                    if pub_date > end_date:
                        continue
                    if not href.startswith("http"):
                        href = BASE_URL + href
                    items.append((title, href, pub_date))

            if not items and page_exhausted:
                break
            if not items:
                break

            for title, detail_url, pub_date in items:
                total += 1
                record_id = make_id(title, pub_date, self.SITE_NAME)
                nt = infer_notice_type(title)
                enriched = {}
                try:
                    detail_html = get_html(detail_url)
                    enriched = parse_html_detail(detail_html, nt)
                except Exception:
                    pass
                record = {
                    "id": record_id, "site": self.SITE_KEY,
                    "notice_type": nt,
                    "source_url": BASE_URL, "detail_url": detail_url,
                    "publish_date": pub_date, "project_name": title,
                    "budget": enriched.get("budget"),
                    "budget_text": enriched.get("budget_text"),
                    "budget_unit": enriched.get("budget_unit"),
                    "purchaser": enriched.get("purchaser"),
                    "purchaser_raw": "",
                    "open_date": enriched.get("open_date"),
                    "deadline": enriched.get("deadline"),
                    "expected_list": enriched.get("expected_list"),
                    "winner": enriched.get("winner"),
                    "winning_amount": enriched.get("winning_amount"),
                    "region": "盐城市", "district_code": "",
                    "raw_json": json.dumps({"cat": cat_name}, ensure_ascii=False),
                    "detail_fetched": 1,
                }
                if self.save(record):
                    new += 1
                time.sleep(0.3)

            time.sleep(0.5)
        logger.info(f"[{self.SITE_NAME}] {cat_name}: {total}条 新增{new}条")
        return {"total": total, "new": new}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = YuedaCrawlerPro()
    s, e = "2026-06-01", datetime.now().strftime("%Y-%m-%d")
    r = c.crawl_all(s, e)
    print(f"总计: {r['total']} 新增: {r['new']}")

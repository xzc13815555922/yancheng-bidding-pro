#!/usr/bin/env python3
"""盐城市东方集团 Pro 采集器 — www.orientalgroup.net.cn"""
import json, logging, os, re, sys, time
from datetime import datetime
from typing import Dict

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from base import BaseCrawler, make_id
from html_common import get_html, infer_notice_type, extract_date, save_page_md

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from enrich_details import parse_html_detail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.orientalgroup.net.cn"
CATEGORIES = [
    ("/zbzl/qzzgs/", "全资子公司公告", "tender"),
    ("/zbzl/zbgg/",  "招标公告", "tender"),
    ("/zbzl/zbgs/",  "招标公示", "award"),
]


class DongfangCrawlerPro(BaseCrawler):
    SITE_KEY  = "dongfang"
    SITE_NAME = "盐城市东方集团"

    def crawl_all(self, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for path, cat_name, ntype in CATEGORIES:
            r = self._crawl_category(path, cat_name, start_date, end_date)
            total += r["total"]; new += r["new"]
        return {"total": total, "new": new}

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for path, cat_name, ntype in CATEGORIES:
            r = self._crawl_category(path, cat_name, start_date, end_date)
            total += r["total"]; new += r["new"]
        return {"total": total, "new": new}

    def _crawl_category(self, base_path: str, cat_name: str,
                         start_date: str, end_date: str) -> Dict:
        total = new = 0
        for page in range(1, 30):
            if page == 1:
                url = BASE_URL + base_path
            else:
                url = BASE_URL + base_path + f"index_{page}.html"
            try:
                html = get_html(url)
            except Exception as e:
                logger.debug(f"dongfang {cat_name} p{page}: {e}")
                break

            soup = BeautifulSoup(html, "lxml")
            items = []
            page_exhausted = False
            for li in soup.find_all("li"):
                a = li.find("a", href=True)
                if not a:
                    continue
                href = a["href"]
                title = a.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                m = re.search(r'/(\d{4}-\d{2}-\d{2})/', href)
                if not m:
                    continue
                pub_date = m.group(1)
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
                enriched = {}
                enriched = {}
                page_path = None
                try:
                    detail_html = get_html(detail_url)
                    page_path = save_page_md(detail_html, detail_url, self.SITE_KEY, title)
                    enriched = parse_html_detail(detail_html, infer_notice_type(title))
                except Exception:
                    pass
                record = {
                    "id": record_id, "site": self.SITE_KEY,
                    "notice_type": infer_notice_type(title),
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
                    "page_path": page_path,
                }
                if self.save(record):
                    new += 1
                time.sleep(0.3)

            time.sleep(0.5)
        logger.info(f"[{self.SITE_NAME}] {cat_name}: {total}条 新增{new}条")
        return {"total": total, "new": new}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = DongfangCrawlerPro()
    s, e = "2026-06-01", datetime.now().strftime("%Y-%m-%d")
    r = c.crawl_all(s, e)
    print(f"总计: {r['total']} 新增: {r['new']}")

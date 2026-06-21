#!/usr/bin/env python3
"""盐城市都市建设投资集团 Pro 采集器 — www.ycdsjt.cn"""
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

BASE_URL = "http://www.ycdsjt.cn"
# 分页: /?zhaobiao/ p1, /?zhaobiao_2/ p2, ...
CATEGORIES = [
    ("zhaobiao", "招标"),
    ("tongzhi",  "通知"),
]


def _page_url(cat: str, page: int) -> str:
    if page == 1:
        return f"{BASE_URL}/?{cat}/"
    return f"{BASE_URL}/?{cat}_{page}/"


class DushiCrawlerPro(BaseCrawler):
    SITE_KEY  = "dushi"
    SITE_NAME = "盐城市都市建设投资集团"

    def crawl_all(self, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for cat, cat_name in CATEGORIES:
            r = self._crawl_category(cat, cat_name, start_date, end_date)
            total += r["total"]; new += r["new"]
        return {"total": total, "new": new}

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for cat, cat_name in CATEGORIES:
            r = self._crawl_category(cat, cat_name, start_date, end_date)
            total += r["total"]; new += r["new"]
        return {"total": total, "new": new}

    def _crawl_category(self, cat: str, cat_name: str, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for page in range(1, 30):
            url = _page_url(cat, page)
            try:
                html = get_html(url)
            except Exception as e:
                logger.debug(f"dushi {cat_name} p{page}: {e}")
                break

            soup = BeautifulSoup(html, "lxml")
            newslist = soup.find("div", class_="newslist")
            if not newslist:
                break

            items = []
            page_exhausted = False
            for dl in newslist.find_all("dl"):
                dt = dl.find("dt")
                dd = dl.find("dd")
                if not dt:
                    continue
                a = dt.find("a", href=True)
                if not a:
                    continue
                href = a["href"]
                title = a.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                if not href.endswith(".html") and not href.endswith(".shtml"):
                    continue
                # date from dd: "272026-05" → 2026-05-27
                dd_text = dd.get_text(strip=True) if dd else ""
                m = re.match(r'(\d{2})(\d{4})-(\d{2})', dd_text)
                if m:
                    pub_date = f"{m.group(2)}-{m.group(3)}-{m.group(1)}"
                else:
                    pub_date = extract_date(dd_text)
                if not pub_date:
                    continue
                if pub_date < start_date:
                    page_exhausted = True
                    continue
                if pub_date > end_date:
                    continue
                if not href.startswith("http"):
                    href = BASE_URL + href
                items.append((title, href, pub_date, dl.get_text(" ", strip=True)))

            if not items and page_exhausted:
                break
            if not items:
                break

            for title, detail_url, pub_date, list_text in items:
                total += 1
                record_id = make_id(title, pub_date, self.SITE_NAME)
                ntype = infer_notice_type(title)
                enriched = {}
                enriched = {}
                page_path = None
                try:
                    detail_html = get_html(detail_url)
                    page_path = save_page_md(detail_html, detail_url, self.SITE_KEY, title)
                    enriched = parse_html_detail(detail_html, ntype)
                except Exception:
                    pass
                # open_date from list text (faster than detail page)
                if not enriched.get("open_date"):
                    om = re.search(
                        r'开\s*标\s*时\s*间[：:]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})\s*时(?:\s*(\d{1,2})\s*分)?',
                        list_text
                    )
                    if om:
                        mn = om.group(5) or "00"
                        enriched["open_date"] = (
                            f"{om.group(1)}-{om.group(2).zfill(2)}-{om.group(3).zfill(2)} "
                            f"{om.group(4).zfill(2)}:{mn.zfill(2)}:00"
                        )
                record = {
                    "id": record_id, "site": self.SITE_KEY,
                    "notice_type": ntype,
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
    c = DushiCrawlerPro()
    s, e = "2026-06-01", datetime.now().strftime("%Y-%m-%d")
    r = c.crawl_all(s, e)
    print(f"总计: {r['total']} 新增: {r['new']}")

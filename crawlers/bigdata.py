#!/usr/bin/env python3
"""盐城市大数据集团 Pro 采集器 — www.ycdatagroup.cn"""
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

BASE_URL = "https://www.ycdatagroup.cn"
# 招标公告分类 → notice_type
CATEGORIES = [
    ("/news/19.html", "招标公告", "tender"),
    ("/news/20.html", "中标公示", "award"),
]
KEYWORDS = {"公告", "中标", "结果", "公示", "招标", "采购"}


class BigdataCrawlerPro(BaseCrawler):
    SITE_KEY  = "bigdata"
    SITE_NAME = "盐城市大数据集团"

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for path, cat_name, ntype in CATEGORIES:
            if notice_type and ntype != notice_type:
                continue
            r = self._crawl_category(path, cat_name, ntype, start_date, end_date)
            total += r["total"]; new += r["new"]
        return {"total": total, "new": new}

    def _crawl_category(self, start_path: str, cat_name: str, ntype: str,
                         start_date: str, end_date: str) -> Dict:
        total = new = 0
        # 网站每页10条，无明显多页（仅展示最近10条）
        # 尝试 index_2.html ... 最多10页
        for page in range(1, 11):
            if page == 1:
                url = BASE_URL + start_path
            else:
                # 尝试 /news/19_2.html 等
                url = BASE_URL + re.sub(r'\.html$', f'_{page}.html', start_path)
            try:
                html = get_html(url)
            except Exception as e:
                logger.debug(f"bigdata {cat_name} p{page}: {e}")
                break
            if len(html) < 500:
                break

            soup = BeautifulSoup(html, "lxml")
            items = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("/news/show-"):
                    continue
                h3 = a.find("h3")
                title = h3.get_text(strip=True) if h3 else a.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                if not any(kw in title for kw in KEYWORDS):
                    continue
                items.append((title, BASE_URL + href))

            if not items:
                break

            for title, detail_url in items:
                total += 1
                enriched = {}
                enriched = {}
                page_path = None
                pub_date = ""
                try:
                    detail_html = get_html(detail_url)
                    page_path = save_page_md(detail_html, detail_url, self.SITE_KEY, title)
                    # extract date from detail page .time element
                    dsoup = BeautifulSoup(detail_html, "lxml")
                    time_el = dsoup.find(class_="time")
                    if time_el:
                        pub_date = extract_date(time_el.get_text())
                    enriched = parse_html_detail(detail_html, ntype)
                except Exception:
                    pass
                if not pub_date:
                    continue
                if pub_date < start_date or pub_date > end_date:
                    continue
                record_id = make_id(title, pub_date, self.SITE_NAME)
                notice_type_val = infer_notice_type(title)
                record = {
                    "id": record_id, "site": self.SITE_KEY,
                    "notice_type": notice_type_val,
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
                    "region": "盐南高新区", "district_code": "",
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
    c = BigdataCrawlerPro()
    s, e = "2026-06-01", datetime.now().strftime("%Y-%m-%d")
    r = c.crawl_all(s, e)
    print(f"总计: {r['total']} 新增: {r['new']}")

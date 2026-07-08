#!/usr/bin/env python3
"""江苏世纪新城 Pro 采集器 — jscncg.com"""
import json, logging, os, re, sys, time
from datetime import datetime
from typing import Dict

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from base import BaseCrawler, make_id
from html_common import get_html, infer_notice_type, save_page_md

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from enrich_details import parse_html_detail

logger = logging.getLogger(__name__)

BASE_URL = "https://jscncg.com"
LIST_PATH = "/tenderLease/tender/"


class JscnCrawlerPro(BaseCrawler):
    SITE_KEY  = "jscn"
    SITE_NAME = "江苏世纪新城"

    def crawl_all(self, start_date: str, end_date: str) -> Dict:
        return self._crawl(start_date, end_date)

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        return self._crawl(start_date, end_date)

    def _crawl(self, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for page in range(1, 50):
            url = (BASE_URL + LIST_PATH) if page == 1 else (BASE_URL + LIST_PATH + f"index_{page}.html")
            try:
                html = get_html(url)
            except Exception as e:
                logger.debug(f"jscn p{page}: {e}")
                break

            soup = BeautifulSoup(html, "lxml")
            items = []
            page_exhausted = False
            for li in soup.find_all("li", myid=True):
                a = li.find("a", href=True)
                if not a:
                    continue
                href = a["href"]
                title = a.get_text(strip=True)
                m = re.match(r'/tenderLease/tender/(\d{4}-\d{2}-\d{2})/\d+\.html', href)
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

            # 修复翻页 bug：区分"页空"和"页有但全过滤空"两种场景
            # - page_exhausted=True 表示这页有比 start_date 更老的数据（翻过头了）→ break
            # - 移除原来的 "if not items: break"：避免 page 1 全 > end_date 时立即退出
            #   （例如回填 1-4 月时 page 1 全是 6 月数据，items 过滤后为空但实际翻到 page 5+ 才有 1-4 月数据）
            # 外层 for page in range(1, 50) 已限制最大页数
            if not items and page_exhausted:
                break

            for title, detail_url, pub_date in items:
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
                except Exception as e:
                    logger.warning(f'[save_record_silent_fail] L83 {e}')
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
                    "raw_json": json.dumps({}, ensure_ascii=False),
                    "detail_fetched": 1,
                    "page_path": page_path,
                }
                if self.save(record):
                    new += 1
                time.sleep(0.3)

            time.sleep(0.5)
        logger.info(f"[{self.SITE_NAME}]: {total}条 新增{new}条")
        return {"total": total, "new": new}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = JscnCrawlerPro()
    s, e = "2026-06-01", datetime.now().strftime("%Y-%m-%d")
    r = c.crawl_all(s, e)
    print(f"总计: {r['total']} 新增: {r['new']}")

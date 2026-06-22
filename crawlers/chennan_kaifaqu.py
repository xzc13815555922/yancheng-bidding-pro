#!/usr/bin/env python3
"""
城南新区公共资源交易网 & 开发区公共资源交易网 Pro 采集器
两站共用 ewb 系统，分页规则相同:
  page 1  → BASE/jyxx/tradeInfo.html (chennan) / BASE/jyxx/about.html (kaifaqu)
  page N  → BASE/jyxx/{N}.html  (N=2..19 直链, N>=20 JS verify – 跳过)
UUID路径: /jyxx/CATCODE1/CATCODE2/YYYYMMDD/UUID.html
"""
import json, logging, os, re, sys, time
from datetime import datetime
from typing import Dict, Tuple

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from base import BaseCrawler, make_id
from html_common import get_html, infer_notice_type, save_page_md

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from enrich_details import parse_html_detail

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(r'/jyxx/(\d+)/(\d+)/(\d{8})/[a-f0-9\-]+\.html')


def _parse_uuid_date(href: str) -> Tuple[str, str, str]:
    """返回 (pub_date, catcode1, catcode2) 或空字符串。"""
    m = UUID_PATTERN.match(href)
    if not m:
        return "", "", ""
    d = m.group(3)
    return f"{d[:4]}-{d[4:6]}-{d[6:]}", m.group(1), m.group(2)


def _infer_type_from_cat(catcode2: str, title: str) -> str:
    """根据子目录代码 + 标题推断 notice_type。"""
    # 末位数字: 1=招标 2=资格 3=澄清 4=候选人 5=中标/成交 6=终止 7=合同
    last = catcode2[-1] if catcode2 else ""
    if last in ("4", "5") or "中标" in catcode2 or "成交" in catcode2:
        return "award"
    if last in ("3", "6"):
        return "other"
    return infer_notice_type(title)


def _ewb_crawl(site_key: str, site_name: str, base_url: str, list_path: str,
                region: str, district_code: str,
                start_date: str, end_date: str,
                db_saver) -> Dict:
    """通用 ewb 系统采集逻辑。"""
    total = new = 0
    # page 1 special URL, pages 2..19 /jyxx/N.html
    for page in range(1, 20):
        url = (base_url + list_path) if page == 1 else (base_url + f"/jyxx/{page}.html")
        try:
            html = get_html(url)
        except Exception as e:
            logger.debug(f"{site_name} p{page}: {e}")
            break

        soup = BeautifulSoup(html, "lxml")
        items = []
        page_exhausted = False
        for a in soup.find_all("a", href=True):
            href = a["href"]
            pub_date, cat1, cat2 = _parse_uuid_date(href)
            if not pub_date:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 4:
                continue
            if pub_date < start_date:
                page_exhausted = True
                continue
            if pub_date > end_date:
                continue
            if not href.startswith("http"):
                href = base_url + href
            ntype = _infer_type_from_cat(cat2, title)
            items.append((title, href, pub_date, ntype))

        # 修复翻页 bug：区分"页空"和"页有但全过滤空"两种场景
        # - page_exhausted=True 表示这页有比 start_date 更老的数据（翻过头了）→ break
        # - 移除原来的 "if not items: break"：避免 page 1 全 > end_date 时立即退出
        #   （例如回填 1-4 月时 page 1 全是 6 月数据，items 过滤后为空但实际翻到 page 5+ 才有 1-4 月数据）
        # 外层 for page in range(1, 20) 已限制最大页数
        if not items and page_exhausted:
            break

        for title, detail_url, pub_date, ntype in items:
            total += 1
            record_id = make_id(title, pub_date, site_name)
            enriched = {}
            page_path = None
            try:
                detail_html = get_html(detail_url)
                page_path = save_page_md(detail_html, detail_url, site_key, title)
                enriched = parse_html_detail(detail_html, ntype)
            except Exception:
                pass
            record = {
                "id": record_id, "site": site_key,
                "notice_type": ntype,
                "source_url": base_url, "detail_url": detail_url,
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
                "region": region, "district_code": district_code,
                "raw_json": json.dumps({}, ensure_ascii=False),
                "detail_fetched": 1,
                "page_path": page_path,
            }
            if db_saver(record):
                new += 1
            time.sleep(0.2)

        time.sleep(0.5)
    logger.info(f"[{site_name}] 总计{total}条 新增{new}条")
    return {"total": total, "new": new}


class ChengnanCrawlerPro(BaseCrawler):
    SITE_KEY  = "chennan"
    SITE_NAME = "城南新区公共资源交易网"
    BASE_URL  = "http://221.231.11.22:8099"
    LIST_PATH = "/jyxx/tradeInfo.html"

    def crawl_all(self, start_date: str, end_date: str) -> Dict:
        return _ewb_crawl(
            self.SITE_KEY, self.SITE_NAME, self.BASE_URL, self.LIST_PATH,
            "盐南高新区", "320971",
            start_date, end_date, self.save
        )

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        return _ewb_crawl(
            self.SITE_KEY, self.SITE_NAME, self.BASE_URL, self.LIST_PATH,
            "盐南高新区", "320971",
            start_date, end_date, self.save
        )


class KaifaquCrawlerPro(BaseCrawler):
    SITE_KEY  = "kaifaqu"
    SITE_NAME = "开发区公共资源交易网"
    BASE_URL  = "http://218.92.181.186:8081"
    LIST_PATH = "/jyxx/about.html"

    def crawl_all(self, start_date: str, end_date: str) -> Dict:
        return _ewb_crawl(
            self.SITE_KEY, self.SITE_NAME, self.BASE_URL, self.LIST_PATH,
            "经开区", "320941",
            start_date, end_date, self.save
        )

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        return _ewb_crawl(
            self.SITE_KEY, self.SITE_NAME, self.BASE_URL, self.LIST_PATH,
            "经开区", "320941",
            start_date, end_date, self.save
        )


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", choices=["chennan", "kaifaqu", "all"], default="all")
    args = parser.parse_args()

    s, e = "2026-06-01", datetime.now().strftime("%Y-%m-%d")
    if args.site in ("chennan", "all"):
        c = ChengnanCrawlerPro()
        r = c.crawl_all(s, e)
        print(f"[chennan] 总计: {r['total']} 新增: {r['new']}")
    if args.site in ("kaifaqu", "all"):
        c2 = KaifaquCrawlerPro()
        r2 = c2.crawl_all(s, e)
        print(f"[kaifaqu] 总计: {r2['total']} 新增: {r2['new']}")

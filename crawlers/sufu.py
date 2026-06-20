#!/usr/bin/env python3
"""苏服采（js.fwgov.cn）Pro 采集器
API: POST https://js.fwgov.cn:868/purchases/tenders/notice/announcementResultListNew
可采类型: type=2(更正) type=3(成交/award) type=4(合同)
招标公告(announcementListNew)需登录，返回403，不可采。
budget字段已是元，无需换算。
"""
import json, logging, re, sys, time
from datetime import datetime
from typing import Dict

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from base import BaseCrawler, make_id

logger = logging.getLogger(__name__)

BASE_API = "https://js.fwgov.cn:868"
ENDPOINT = "/purchases/tenders/notice/announcementResultListNew"
AREA_CODE = ["3209"]          # 盐城市
PAGE_SIZE = 10                # API上限
SLEEP_SEC = 0.5

HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://js.fwgov.cn/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# type → notice_type
TYPE_MAP = {
    "2": "other",   # 更正公告
    "3": "award",   # 成交公告
    "4": "other",   # 合同公告
}

# serviceType
SERVICE_TYPES = ["1", "2"]   # 1=服务类 2=货物类


class SufuCrawlerPro(BaseCrawler):
    SITE_KEY  = "sufu"
    SITE_NAME = "苏服采"

    def crawl_all(self, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for stype in SERVICE_TYPES:
            for atype in TYPE_MAP:
                r = self._crawl_type(atype, stype, start_date, end_date)
                total += r["total"]
                new   += r["new"]
        return {"total": total, "new": new}

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        return self.crawl_all(start_date, end_date)

    def _crawl_type(self, atype: str, stype: str, start_date: str, end_date: str) -> Dict:
        total = new = 0
        page = 1
        while True:
            body = {
                "type": atype,
                "sort": "releaseTime",
                "order": "desc",
                "pageNumber": page,
                "pageSize": PAGE_SIZE,
                "areaCode": AREA_CODE,
                "serviceType": stype,
            }
            try:
                resp = requests.post(
                    BASE_API + ENDPOINT, json=body, headers=HEADERS, timeout=15
                )
                data = resp.json()
            except Exception as e:
                logger.warning(f"[苏服采] type={atype} stype={stype} p{page}: {e}")
                break

            result  = data.get("result") or {}
            records = result.get("records") or []
            if not records:
                break

            page_exhausted = False
            for rec in records:
                release = rec.get("releaseTime", "")
                pub_date = release[:10] if release else ""
                if not pub_date:
                    continue
                if pub_date < start_date:
                    page_exhausted = True
                    continue
                if pub_date > end_date:
                    continue

                total += 1
                rec_id = str(rec.get("id", ""))
                ntype  = TYPE_MAP.get(str(rec.get("type", "")), "other")

                # 项目名: itemName 更简洁，title 包含公告类型后缀
                proj = rec.get("itemName") or rec.get("title") or ""

                budget = rec.get("itemBudget")          # 已是元
                tx_price = rec.get("transactionPrice")
                winning_amount = f"{float(tx_price):.2f}" if tx_price else None

                purchaser = rec.get("procurementUnit") or ""
                # 去掉末尾的括号备注 "盐南高新区黄海街道（单位）" → "盐南高新区黄海街道"
                purchaser = re.sub(r"（[^）]{1,6}）$", "", purchaser).strip()

                area_code = str(rec.get("areaCode", ""))
                detail_url = (
                    f"https://js.fwgov.cn/biddingResults?id={atype}&serviceType={stype}"
                )

                notice = {
                    "id": make_id(proj or rec_id, pub_date, self.SITE_NAME),
                    "site": self.SITE_KEY,
                    "notice_type": ntype,
                    "source_url": f"https://js.fwgov.cn/biddingResults?id={atype}&serviceType={stype}",
                    "detail_url": detail_url,
                    "publish_date": pub_date,
                    "project_name": proj,
                    "budget": budget,
                    "budget_text": f"{budget:.0f}元" if budget is not None else None,
                    "budget_unit": "元" if budget is not None else None,
                    "purchaser": purchaser or None,
                    "purchaser_raw": rec.get("procurementUnit") or "",
                    "open_date": None,
                    "deadline": rec.get("tenderEndTime"),
                    "expected_list": None,
                    "winner": None,       # 列表API不含中标供应商，详情API需登录
                    "winning_amount": winning_amount,
                    "region": "盐城市",
                    "district_code": area_code,
                    "raw_json": json.dumps(
                        {"type": atype, "serviceType": stype, "itemNo": rec.get("itemNo"), "id": rec_id},
                        ensure_ascii=False,
                    ),
                    "detail_fetched": 1,
                }
                if self.save(notice):
                    new += 1

            time.sleep(SLEEP_SEC)

            # 翻页终止条件
            if page_exhausted and not [r for r in records if (r.get("releaseTime","")[:10]) >= start_date]:
                break
            if len(records) < PAGE_SIZE:
                break
            cur   = result.get("current", page)
            pages = result.get("pages", 1)
            if cur >= pages:
                break
            page += 1

        logger.info(f"[苏服采] type={atype} stype={stype}: {total}条 新增{new}条")
        return {"total": total, "new": new}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = SufuCrawlerPro()
    s, e = "2026-06-01", datetime.now().strftime("%Y-%m-%d")
    r = c.crawl_all(s, e)
    print(f"总计: {r['total']} 新增: {r['new']}")

#!/usr/bin/env python3
"""苏服采（js.fwgov.cn）Pro 采集器
API: POST https://js.fwgov.cn:868/purchases/tenders/notice/page

2026-07-20 重写（向旧版 bidding-assistant/sufu_crawler_final.py 学习）：
  - 旧版 endpoint 是 /announcementResultListNew（结果公告），只能采 type=2/3/4，
    招标公告（biddingStatus=1/2）拿不到，导致 unified.db 7 月苏服务 tender=0。
  - 修复：换 /notice/page（招标公告列表），用 biddingStatus="" 不限状态，
    areaCode=320992（盐南高新区）/320991（经开区），serviceType 1+2（服务+货物）。
  - 实测 7/1-7/20: 盐南 39 + 经开 15 = 54 条，biddingStatus=1(招标中)16 条 + 2(其他)38 条。
  - budget 字段 itemBudget 已是元，无需换算。
"""
import json
import logging
import re
import sys
import time
from datetime import datetime
from typing import Dict

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from base import BaseCrawler, make_id

logger = logging.getLogger(__name__)

BASE_API = "https://js.fwgov.cn:868"
ENDPOINT = "/purchases/tenders/notice/page"

# 区域代码（旧版 bidding-assistant 验证可用；3209=盐城市全市太大，应细化到区县）
# 320992=盐南高新区, 320991=经开区
AREA_CODES = ["320992", "320991"]
PAGE_SIZE = 20
SLEEP_SEC = 0.5

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://js.fwgov.cn",
    "Referer": "https://js.fwgov.cn/bidding?serviceType=1",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# serviceType：1=服务类 2=货物类（CEO 2026-07-20 拍板：服务+货物都采）
SERVICE_TYPES = ["1", "2"]

# 区域代码 → 区域名（写入 notices.region 字段，供 add_std_district.py 推导 std_district）
AREA_NAME_MAP = {
    "320992": "盐南高新区",
    "320991": "经开区",
}


class SufuCrawlerPro(BaseCrawler):
    SITE_KEY  = "sufu"
    SITE_NAME = "苏服采"

    def crawl_all(self, start_date: str, end_date: str) -> Dict:
        total = new = 0
        for area in AREA_CODES:
            for stype in SERVICE_TYPES:
                r = self._crawl_area(area, stype, start_date, end_date)
                total += r["total"]
                new   += r["new"]
        return {"total": total, "new": new}

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        """兼容 base.py 接口：notice_type 任意值都走全量采集"""
        return self.crawl_all(start_date, end_date)

    def _crawl_area(self, area: str, stype: str, start_date: str, end_date: str) -> Dict:
        total = new = 0
        page = 1
        area_name = AREA_NAME_MAP.get(area, "盐城市")

        while True:
            body = {
                "samEnterprises": "",
                "biddingStatus": "",          # 关键：不限状态，1=招标中 2=其他
                "itemBudgetStart": "",
                "itemBudgetEnd": "",
                "sort": "",
                "order": "",
                "nameOrunit": "",
                "pageNumber": page,
                "pageSize": PAGE_SIZE,
                "areaCode": [area],
                "serviceType": stype,
            }
            try:
                resp = requests.post(
                    BASE_API + ENDPOINT, json=body, headers=HEADERS, timeout=15
                )
                data = resp.json()
            except Exception as e:
                logger.warning(f"[苏服采] area={area} stype={stype} p{page}: {e}")
                break

            result  = data.get("result") or {}
            records = result.get("records") or []
            if not records:
                break

            page_exhausted = False
            for rec in records:
                release = rec.get("publishTime", "")
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
                # 苏服采本接口全是招标公告 → notice_type=tender
                ntype = "tender"

                # 项目名: itemName 更简洁
                proj = rec.get("itemName") or rec.get("title") or ""

                budget = rec.get("itemBudget")  # 已是元
                budget_text = f"{float(budget):.0f}元" if budget is not None else None

                purchaser = rec.get("procurementUnit") or ""
                # 去掉末尾的括号备注 "盐南高新区黄海街道（单位）" → "盐南高新区黄海街道"
                purchaser = re.sub(r"（[^）]{1,6}）$", "", purchaser).strip()

                # detail_url: 旧版格式 https://js.fwgov.cn/bidding details?id=...
                # 用空格保持与 6 月历史数据一致（raw_json 有这条记录）
                detail_url = f"https://js.fwgov.cn/bidding details?id={rec_id}"

                notice = {
                    "id": make_id(proj or rec_id, pub_date, self.SITE_NAME),
                    "site": self.SITE_KEY,
                    "notice_type": ntype,
                    "source_url": f"https://js.fwgov.cn/bidding?serviceType={stype}",
                    "detail_url": detail_url,
                    "publish_date": pub_date,
                    "project_name": proj,
                    "budget": budget,
                    "budget_text": budget_text,
                    "budget_unit": "元" if budget is not None else None,
                    "purchaser": purchaser or None,
                    "purchaser_raw": rec.get("procurementUnit") or "",
                    "open_date": None,
                    "deadline": rec.get("tenderEndTime"),
                    "expected_list": None,
                    "winner": None,
                    "winning_amount": None,
                    "region": area_name,                 # 关键：写入区域名供 add_std_district 推导
                    "district_code": area,                # 320992/320991 区县码
                    "raw_json": json.dumps(
                        {
                            "id": rec_id,
                            "itemNo": rec.get("itemNo"),
                            "serviceType": stype,
                            "biddingStatus": rec.get("biddingStatus"),
                            "terminationStatus": rec.get("terminationStatus"),
                            "full_record": rec,
                        },
                        ensure_ascii=False,
                    ),
                    "detail_fetched": 1,
                }
                if self.save(notice):
                    new += 1

            time.sleep(SLEEP_SEC)

            # 翻页终止：服务端 total 字段
            server_total = result.get("total", 0)
            if page * PAGE_SIZE >= server_total:
                break
            if len(records) < PAGE_SIZE:
                break
            page += 1

        logger.info(
            f"[苏服采] area={area_name} stype={stype}: {total}条 新增{new}条"
        )
        return {"total": total, "new": new}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    c = SufuCrawlerPro()
    s, e = "2026-06-01", datetime.now().strftime("%Y-%m-%d")
    r = c.crawl_all(s, e)
    print(f"总计: {r['total']} 新增: {r['new']}")
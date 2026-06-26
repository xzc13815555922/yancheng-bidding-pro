#!/usr/bin/env python3
"""jszbcg 站点详情补全：从 raw_json 直接映射字段，无需 HTTP。"""
import json
from typing import Dict

from html_common import parse_datetime


def enrich_from_raw_json(raw_json: str, notice_type: str) -> Dict:
    """jszbcg: 23 列已在 raw_json，直接映射。"""
    result = {}
    try:
        d = json.loads(raw_json)
    except Exception:
        return result

    purchaser = d.get("projectCompany") or ""
    if purchaser:
        result["purchaser"] = purchaser
        result["purchaser_raw"] = purchaser

    # openBidTime 是 API 的"发布/接收时间"，作为 tender open_date 的最佳近似
    open_bid = d.get("openBidTime") or ""
    if open_bid and notice_type == "tender":
        result["open_date"] = parse_datetime(open_bid)

    # bulletinType=3 成交公告：API 无中标单位/金额，需 PDF 解析（由调用方降级处理）
    return result

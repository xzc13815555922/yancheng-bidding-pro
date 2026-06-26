#!/usr/bin/env python3
"""苏服务(sufu) 站点详情补全：迁移时关键字段已存入 raw_json，从这里读回。"""
import json
from typing import Dict


def enrich_from_raw_json(raw_json: str, record_row) -> Dict:
    result = {}
    try:
        d = json.loads(raw_json)
    except Exception:
        d = {}

    budget = d.get("budget") or record_row["budget"]
    if budget and float(budget) > 0:
        result["budget"] = float(budget)
        result["budget_unit"] = d.get("budget_unit") or record_row["budget_unit"] or "元"

    deadline = d.get("deadline") or record_row["deadline"]
    if deadline:
        result["deadline"] = deadline

    open_dt = d.get("opening_time")
    if open_dt:
        result["open_date"] = open_dt

    purchaser = d.get("purchaser") or record_row["purchaser_raw"]
    if purchaser:
        result["purchaser"] = purchaser
    return result

#!/usr/bin/env python3
"""
苏服务(sufu) 站点详情补全：迁移时关键字段已存入 raw_json，从这里读回。

【2026-07-23 P0-1 修复】小标：open_date 字段名兜底
背景: sufu 列表 API (/notice/page) 返回的是 full_record.tenderStartTime
但 sufu.py 第 149 行 hardcode open_date=None, sufu_parser 之前只读 d.get('opening_time')
导致 7 月新采 58 条 tender open_date 全空, verify_quality FAIL 38%
修复: 增加 full_record.tenderStartTime 路径兜底
"""
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

    # open_date 字段名兜底链:
    #   1. d['opening_time']       — 旧版/外部预期 key（极少命中）
    #   2. d['full_record']['tenderStartTime'] — sufu 列表 API 实际返回字段 ✅
    #   3. record_row fallback     — 已有的 open_date（最后一次兜底）
    open_dt = d.get("opening_time")
    if not open_dt:
        fr = d.get("full_record") or {}
        open_dt = fr.get("tenderStartTime")
    if not open_dt:
        open_dt = record_row["open_date"]
    if open_dt:
        result["open_date"] = open_dt

    purchaser = d.get("purchaser") or record_row["purchaser_raw"]
    if purchaser:
        result["purchaser"] = purchaser
    return result

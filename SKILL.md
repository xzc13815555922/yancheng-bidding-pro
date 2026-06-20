---
name: yancheng-bidding-pro
description: 全域盐城招标数据采集（12站/1764条）；触发词：全域招标 / 盐城招标 / 招标采集Pro；输出 Excel 发飞书给 azE
outputs:
  - excel   # 盐城市全域招标信息_vN_YYYYMMDD_HHMM.xlsx
  - sqlite  # data/*.db（12个站点独立数据库）
version: v1.0
status: 生产可用
last_run: 2026-06-19
records: 1764条（12站）
---

# 全域招标信息采集 Pro

## 概述

采集盐城市 12 个站点的招标/中标公告，输出带 purchaser/budget/winner 的 Excel。

**覆盖站点**：jszbcg（江苏政府采购）、yancheng_gov、ycggzy、sufu、yueda、dushi、jscn、chennan、dongfang、bigdata、jingkai、kaifaqu

## 工作流程

```bash
cd ~/.openclaw/workspace/yancheng-bidding-pro

# 第一步：增量采集新记录（近3天）
python3 run_collection.py --days 3

# 第二步：HTML 补全（purchaser/budget/open_date/winner）
python3 enrich_details.py

# 第三步：jszbcg PDF OCR（只处理新增 award 无 winner / tender 无 budget）
# 首次全量耗时约 20 分钟，后续增量仅 3-5 分钟
python3 enrich_jszbcg_ocr.py

# 第四步：导出 Excel
python3 export_excel.py

# 第五步：发给 azE
EXCEL=$(ls -t output/*.xlsx | head -1)
cc-connect send --file "$EXCEL" --message "盐城全域招标数据已更新，共$(python3 -c "import sqlite3,glob; print(sum(sqlite3.connect(f).execute('select count(*) from notices').fetchone()[0] for f in glob.glob('data/*.db')))")条"
```

## 注意事项

- jszbcg OCR：图片型 PDF ~40s/条，有 tombstone 保护（每条只 OCR 一次）
- 增量运行时 OCR 很快（新增 10-20 条 × 50% 图片 = 3-5 分钟）
- yancheng_gov 需 Playwright（403 保护），requests 版已标记 detail_fetched=2 跳过
- sufu winner 需登录详情页，暂无法提取

## 输出路径

`~/.openclaw/workspace/yancheng-bidding-pro/output/盐城市全域招标信息_v6_YYYYMMDD_HHMM.xlsx`

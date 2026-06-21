---
name: yancheng-bidding-pro
description: 全域盐城招标数据采集（12站/3920条原始→unified.db 3055条）；触发词：全域招标 / 盐城招标 / 招标采集Pro；输出 unified.db + Excel
outputs:
  - sqlite  # data/unified.db（三张表：tender/award/intention）
  - sqlite  # data/*.db（12个站点独立数据库）
  - excel   # output/盐城市全域招标信息_vN_YYYYMMDD_HHMM.xlsx
version: v1.2
status: 生产可用
last_run: 2026-06-21
records: 3920条原始（12站）→ 发包单位=2892 / 预算=1450 / 中标单位=1257
---

# 全域招标信息采集 Pro

## 概述

采集盐城市 12 个站点的招标/中标/采购意向公告，富化详情页字段，输出 unified.db 三张归一化表 + Excel。

**覆盖站点**：jszbcg（江苏招标采购服务平台）、yancheng_gov、ycggzy、sufu、yueda、dushi、jscn、chennan、dongfang、bigdata、jingkai、kaifaqu

## 工作流程（6步）

```bash
cd ~/.openclaw/workspace/yancheng-bidding-pro

# 第一步：增量采集新记录（近3天）
python3 run_collection.py --days 3

# 第二步：HTML 详情页补全（purchaser/budget/open_date/winner）
python3 enrich_details.py

# 第三步：jszbcg PDF OCR（只处理新增 award 无 winner / tender 无 budget）
# 首次全量耗时约 20 分钟，后续增量仅 3-5 分钟
python3 enrich_jszbcg_ocr.py

# 第四步：区县标准化（std_district）
python3 add_std_district.py

# 第五步：类别打标（std_category）
python3 add_std_category.py

# 第六步：生成 unified.db（三张表）
python3 build_unified.py

# 可选：导出 Excel
python3 export_excel.py

# 可选：发给 azE
EXCEL=$(ls -t output/*.xlsx | head -1)
cc-connect send --file "$EXCEL" --message "盐城全域招标数据已更新"
```

## ycggzy 专用补采（发包单位API补全）

```bash
# ycggzy 是 JS SPA，purchaser 来自列表API，不走 enrich_details
python3 reenrich_ycggzy.py --start 2026-05-01 --end 2026-06-21
```

## 数据质量现状（2026-06-21）

### 全站汇总（3920条原始）

| 字段         | 填充数  | 填充率 |
|------------|--------|------|
| purchaser  | 2892   | 74%  |
| budget     | 1450   | 37%  |
| open_date  | 1133   | 29%  |
| winner     | 1257   | 32%  |
| std_district | ~98% | add_std_district.py |
| std_category | 33%  | 1312/3920，规则持续扩充 |

### 各站概况

| 站点        | 条数  | 发包单位 | 预算 | 开标时间 | 中标单位 |
|-----------|------|--------|-----|--------|--------|
| jszbcg    | 1303 | 462    | 356 | 558    | 571    |
| yancheng_gov | 856 | 787  | 255 | 85     | 132    |
| ycggzy    | 1289 | 1207   | 567 | 344    | 484    |
| sufu      | 194  | 194    | 194 | 47     | 0      |
| yueda     | 84   | 77     | 2   | 49     | 23     |
| dongfang  | 44   | 36     | 18  | 4      | 10     |
| jscn      | 41   | 38     | 12  | 7      | 12     |
| dushi     | 35   | 27     | 14  | 19     | 10     |
| chennan   | 31   | 29     | 15  | 8      | 8      |
| kaifaqu   | 30   | 23     | 12  | 7      | 2      |
| bigdata   | 10   | 10     | 4   | 5      | 4      |
| jingkai   | 3    | 2      | 1   | 0      | 1      |

## 已知结构性限制

- **sufu 中标人 100% 空**：列表API不含，详情API需登录；无法在不提供凭据的情况下修复
- **yueda 中标金额 100% 空**：页面仅发布候选人推荐公示，不含最终成交金额
- **ycggzy purchaser** 来自列表API（`reenrich_ycggzy.py`），不走 `enrich_details.py` 的HTML解析

## 已知遗留问题（待决策）

- **yancheng_gov 10组重复记录**：同名同日期但不同 art_id，均为 other 类型，疑似多标包；is_duplicate 未标记，待用户决定是否合并
- **采购意向 expected_list（预计挂网时间）100% 空**：字段存在但未解析
- **std_category 覆盖率仅 12%**：分类规则定义不足

## 本轮修复清单（2026-06-21）

| # | 问题 | 修复位置 |
|---|------|---------|
| 1 | `infer_notice_type` 漏判"中选"→ 中选公示落入 tender | `crawlers/html_common.py` 加 `"中选"` |
| 2 | `enrich_details.py` WHERE `detail_fetched=0` 漏掉 NULL 记录 | 改为 `IS NULL OR =0` |
| 3 | `base.py` INSERT 时 detail_fetched 写 NULL | 改为 `record.get("detail_fetched", 0)` |
| 4 | yancheng_gov `<!--标题-->` 占位符导致标题乱码（141条） | `_parse_page` 加校验 + `_fetch_detail_title` 从 `<title>` 取标题 |
| 5 | yancheng_gov 被误判为需 Playwright，详情页全部跳过 | 确认 requests 可访问，移除 Playwright-skip block，加入 html_sites |
| 6 | purchaser 漏采"单位名称"标签 | `PURCHASER_KEYWORDS` 加 `"单位名称"` |
| 7 | 政府/管委会类发包单位被 `_ORG_SUFFIX` 漏匹配 | 加 `政府\|管委会` |
| 8 | 都市发包单位在 `<meta name="description">` 中，HTML strip 后丢失 | `_strip_html` 提取 meta description 并拼接到末尾 |
| 9 | 叙述句式发包单位无法提取 | `enrich_details.py` 加三种 fallback regex 格式 |
| 10 | ycggzy 成交公告 winner 漏采（多列供应商名称表格） | `crawlers/ycggzy.py` 加 BeautifulSoup 多列表格解析 |
| 11 | ycggzy transactionInfo-7（国有产权）未采集 | CLASS_CODES 启用，reenrich 覆盖 |
| 12 | ycggzy section/notice_type_raw 新增记录自动回填 | `run_collection.py` `_repair_derived_fields()` |
| 13 | jszbcg OCR 跳过 tender purchaser 未补全记录 | `enrich_jszbcg_ocr.py` WHERE 加 `purchaser IS NULL` |
| 14 | dongfang 预算/发包人抓取失败 | `enrich_details.py` 加"限价"/"发包人"/"关于"前缀清除/首句主语模式 |
| 15 | jszbcg 站点名称错误 | 全局替换为"江苏招标采购服务平台" |

## 注意事项

- jszbcg OCR：图片型 PDF ~40s/条，tombstone 保护（每条只 OCR 一次）
- 增量运行时 OCR 很快（新增 10-20 条 × 50% 图片 ≈ 3-5 分钟）
- yancheng_gov 现在 **不需要 Playwright**，requests 直接访问（2026-06-20 确认）
- `build_unified.py` 会覆写 `data/unified.db`；各站 *.db 保留原始数据

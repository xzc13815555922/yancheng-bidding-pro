---
name: yancheng-bidding-pro
description: 全域盐城招标数据采集（12站/3920条原始→unified.db）；触发词：全域招标 / 盐城招标 / 招标采集Pro；输出 unified.db + Excel
outputs:
  - sqlite  # data/unified.db（三张表：tender/award/intention）
  - sqlite  # data/*.db（12个站点独立数据库）
  - excel   # output/盐城市全域招标信息_vN_YYYYMMDD_HHMM.xlsx
  - pdf     # output/盐开招标公告_YYYYMM.pdf（盐南+经开未分类招标公告月报）
version: v1.5
status: 生产可用
last_run: 2026-06-21
records: 3920条原始（12站）→ 发包单位=3130 / 预算=1538 / 中标单位=1230
---

# 全域招标信息采集 Pro

## 概述

采集盐城市 12 个站点的招标/中标/采购意向公告，富化详情页字段，输出 unified.db 三张归一化表 + Excel。

**覆盖站点**：jszbcg（江苏招标采购服务平台）、yancheng_gov、ycggzy、sufu、yueda、dushi、jscn、chennan、dongfang、bigdata、jingkai、kaifaqu

## 本地缓存架构（v1.4）

所有富化操作均基于本地文件，无需重复联网：

- **jszbcg**：爬虫阶段下载 PDF → 立即转 MD → `data/pages/jszbcg/{项目名}.md`；`enrich_details.py` 直接读 MD
- **其他 HTML 站**：爬虫阶段保存详情页 → `data/pages/{site}/{项目名}.md`，富化直接读本地
- **sufu**：纯 API（`announcementResultListNew`），无需页面
- **ycggzy**：SPA，数据已在列表 API 的 raw_json 中，无需详情页
- 新增记录：第一次采集时自动下载并缓存，后续富化全走本地

## 工作流程（6步）

```bash
cd ~/.openclaw/workspace/yancheng-bidding-pro

# 第一步：增量采集（近3天，jszbcg 同步 PDF→MD，其他站同步下载 HTML→MD）
python3 run_collection.py --days 3

# 第二步：详情页补全（读本地 page_path MD 文件，无则联网并缓存）
python3 enrich_details.py

# 第三步：区县标准化（std_district）
python3 add_std_district.py

# 第四步：类别打标（std_category）
python3 add_std_category.py

# 第五步：生成 unified.db（三张表）
python3 build_unified.py

# 第六步：数据质量验证
python3 verify_quality.py

# 可选：导出 Excel
python3 export_excel.py

# 可选：发给用户
EXCEL=$(ls -t output/*.xlsx | head -1)
cc-connect send --file "$EXCEL" --message "盐城全域招标数据已更新"
```

## 补充工具脚本

```bash
# 批量下载所有站点 HTML 详情页（首次初始化用，断点续传）
python3 download_site_pages.py [--site jscn dongfang ...]

# 批量下载 jszbcg 所有 PDF（首次初始化用，断点续传）
python3 download_jszbcg_pdfs.py

# 按项目名重命名已有 MD 文件
python3 rename_pages.py
```

## ycggzy 专用补采（发包单位 API 补全）

```bash
# ycggzy 是 SPA，purchaser 来自列表 API，不走 enrich_details
python3 reenrich_ycggzy.py --start 2026-05-01 --end 2026-06-21
```

## yancheng_gov Playwright 补全（按需）

yancheng_gov 部分记录因 WAF 返回 403，requests 抓不到，需 Playwright：

```bash
# 轻量版：只处理 detail_fetched=2 的失败记录
python3 enrich_yancheng_gov_playwright.py

# 完整版：Playwright + 表格专项解析，补全率更高
python3 enrich_yancheng_gov.py
```

> 注：大多数 yancheng_gov 记录已能被 requests 直接访问（2026-06-20 确认），
> 只有少量高流量时段的请求需要 Playwright 重试。

## 调试 / 历史工具（非生产流程）

| 脚本 | 说明 | 状态 |
|------|------|------|
| `dry_run_v2.py` | 分类规则只读调试，验证 RULES 命中情况 | 按需 |
| `fix_titles.py` | 修复 yancheng_gov 141条乱码标题 | 已用完 |
| `migrate_from_old.py` | 从旧 history.db 迁移到 Pro DB | 已用完 |

## 数据质量现状（2026-06-21）

### 全站汇总（3920条原始）

| 字段         | 填充数  | 填充率 |
|------------|--------|------|
| purchaser  | 3130   | 80%  |
| budget     | 1538   | 39%  |
| open_date  | 1133   | 29%  |
| winner     | 1230   | 31%  |
| std_district | ~98% | add_std_district.py |
| std_category | 45%  | 规则持续扩充 |

### 各站概况

| 站点           | 条数   | 发包单位 | 预算 | 开标时间 | 中标单位 |
|--------------|------|--------|-----|--------|--------|
| jszbcg       | 1303 | 1300   | 450 | 558    | 544    |
| yancheng_gov | 856  | 787    | 255 | 85     | 132    |
| ycggzy       | 1289 | 1207   | 567 | 344    | 484    |
| sufu         | 194  | 194    | 194 | 47     | 0      |
| yueda        | 84   | 77     | 2   | 49     | 23     |
| dongfang     | 44   | 36     | 18  | 4      | 10     |
| jscn         | 41   | 38     | 12  | 7      | 12     |
| dushi        | 35   | 27     | 14  | 19     | 10     |
| chennan      | 31   | 29     | 15  | 8      | 8      |
| kaifaqu      | 30   | 23     | 12  | 7      | 2      |
| bigdata      | 10   | 10     | 4   | 5      | 4      |
| jingkai      | 3    | 2      | 1   | 0      | 1      |

### 本地缓存覆盖

| 类型 | 数量 | 路径 |
|-----|------|------|
| HTML 详情页 MD | 1130 个 | `data/pages/{site}/` |
| jszbcg PDF | 1300 个（616MB） | `data/pdfs/jszbcg/` |

## 系统不变量（verify_quality.py 自动校验）

以下条件必须始终成立；跌破即为回归，必须排查：

| 不变量 | 当前值 | 说明 |
|--------|-------|------|
| jszbcg 记录数 ≥ 1300 | 1303 | 采集范围退化则告警 |
| yancheng_gov 记录数 ≥ 850 | 856 | — |
| ycggzy 记录数 ≥ 1280 | 1289 | — |
| sufu purchaser 填充率 ≥ 99% | 100% | 纯 API，无理由低于此 |
| jszbcg purchaser 填充率 ≥ 95% | ~99.8% | tenderName API 回填 |
| unified tender/award 各 ≥ 1300 | 1374/1372 | — |
| unified_total ≥ 非other站记录数 × 95% | ✅ | other=流标/更正/终止，不进 unified |

**运行方式**：`python3 verify_quality.py`（run_daily.sh 7/7 步自动运行）

## 已知结构性限制

- **sufu 中标人 100% 空**：列表API不含，详情API需登录，无法修复
- **yueda 预算 97% 空**：网站公告页本身不披露预算金额
- **ycggzy purchaser** 来自列表API（`reenrich_ycggzy.py`），不走 `enrich_details.py`

## 已知遗留问题（待决策）

- **yancheng_gov 10组重复记录**：同名同日期不同 art_id，疑似多标包；is_duplicate 未标记
- **采购意向 expected_list（预计挂网时间）100% 空**：字段存在但未解析
- **std_category 覆盖率 45%**：规则持续扩充中

## 本轮修复清单（v1.4 → v1.5，2026-06-21）

| # | 问题 | 修复位置 |
|---|------|---------|
| 28 | tender 表混入最高限价公示（price_cap）| `build_unified.py` 去掉 price_cap，只保留 tender/requirement |
| 29 | std_category 覆盖率 43%→45%，新增30+关键词 | `add_std_category.py`：餐饮外包/食堂运营/漂浮物/危废处理/外墙整治/劳保用品/财务审计/资产评估/尽职调查/债务融资/主承销商/宣传品制作/媒体合作/主题活动/龙舟赛/苏超/毕业典礼等 |
| 30 | 全资产处置3条规则缺 IT 词保护（must_not 不全）| `add_std_category.py` 土地处置/房屋招租/资产处置补全信息化/数字化/智能化/人工智能排除词 |
| 31 | 新增盐开招标公告月报生成脚本 | `generate_tender_report.py`：按盐南+经开+未分类筛选，输出 PDF |

## 本轮修复清单（v1.3 → v1.4，2026-06-21）

| # | 问题 | 修复位置 |
|---|------|---------|
| 26 | jszbcg 富化依赖单独 OCR 步骤（enrich_jszbcg_ocr.py）| `crawlers/jszbcg.py` 新记录下载 PDF 后立即调 `_pdf_to_md()`，设置 `page_path`；`enrich_details.py` 统一读 MD |
| 27 | run_daily.sh 7步改6步（去掉 enrich_jszbcg_ocr.py 步骤） | `run_daily.sh` |

## 本轮修复清单（v1.2 → v1.3，2026-06-21）

| # | 问题 | 修复位置 |
|---|------|---------|
| 16 | jszbcg purchaser 0%（SPA 无法解析 HTML） | `enrich_jszbcg_ocr.py` 从 Detail API tenderName 回填 |
| 17 | OCR budget 漏匹配"约"前缀（"预算金额约81万元"） | `_parse_ocr_text` regex 改 `[：:\s约]{0,3}` + `parse_html_detail` 双引擎兜底 |
| 18 | jszbcg PDF 未本地缓存，OCR 每次重新下载 | `download_jszbcg_pdfs.py` 全量下载；`enrich_jszbcg_ocr.py` 优先读 `pdf_path` |
| 19 | HTML 详情页未本地缓存，富化每次联网 | `crawlers/html_common.py` 加 `save_page_md()`；7 个爬虫爬取时同步保存 MD |
| 20 | `enrich_details.py` 重富化每次重新请求网络 | 优先读 `page_path` 本地 MD；网络拉取后自动缓存 |
| 21 | jszbcg 新记录需手动单独下载 PDF | `crawlers/jszbcg.py` 新记录 save 后立即调 `_download_pdf()` |
| 22 | `base.py` schema 缺 `page_path`/`pdf_path` | 新增列 + 自动迁移 + INSERT 带这两列 |
| 23 | 本地 MD 文件按 UUID 命名，难以管理 | `rename_pages.py` 按项目名批量重命名；新爬虫直接以项目名命名 |
| 24 | sufu 详情页是 SPA，193 个无效 MD 文件 | 删除无效文件，清除 DB page_path；sufu 已是纯 API 无需页面 |
| 25 | 土地承包/延长30年 未归类 | `add_std_category.py` 加入"土地承包""延长30年""延包试点"→土地处置 |

## v1.2 修复清单（参考）

| # | 问题 | 修复位置 |
|---|------|---------|
| 1 | `infer_notice_type` 漏判"中选" | `html_common.py` |
| 2 | `detail_fetched=0` WHERE 漏 NULL | `enrich_details.py` |
| 3 | `base.py` INSERT detail_fetched 写 NULL | `base.py` |
| 4 | yancheng_gov 标题占位符乱码（141条） | `crawlers/yancheng_gov.py` |
| 5 | yancheng_gov 误判需 Playwright | `enrich_details.py` |
| 6 | purchaser 漏采"单位名称"标签 | `enrich_details.py` |
| 7 | 政府/管委会类被 `_ORG_SUFFIX` 漏匹配 | `enrich_details.py` |
| 8 | 都市发包单位在 meta description 中 | `enrich_details.py` |
| 9 | 叙述句式发包单位无法提取 | `enrich_details.py` |
| 10 | ycggzy 成交公告 winner 漏采多列表格 | `crawlers/ycggzy.py` |
| 11 | ycggzy transactionInfo-7 未采集 | `crawlers/ycggzy.py` |
| 12 | ycggzy section/notice_type_raw 新增未回填 | `run_collection.py` |
| 13 | jszbcg OCR 跳过 tender purchaser 未补全记录 | `enrich_jszbcg_ocr.py` |
| 14 | dongfang 预算/发包人抓取失败 | `enrich_details.py` |
| 15 | jszbcg 站点名称错误 | 全局替换 |

## 注意事项

- jszbcg OCR：图片型 PDF ~40s/条；增量运行只处理新增记录，很快
- 本地缓存后，`enrich_details.py` 和 `enrich_jszbcg_ocr.py` 重跑不联网
- `build_unified.py` 会覆写 `data/unified.db`；各站 *.db 保留原始数据
- `data/` 目录（含 DB、PDF、MD 文件）已加入 `.gitignore`，不随代码提交

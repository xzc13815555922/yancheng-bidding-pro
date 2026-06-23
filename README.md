# 盐城市全域招标信息采集系统 Pro

盐城市 12 个招标网站的数据采集、富化、分类和报告生成系统。

**当前版本**：v2.0 | **数据量**：8322 条（unified.db 三表合计） | **最后更新**：2026-06-23

## 覆盖站点（12个）

| 站点 | 说明 | 采集方式 |
|------|------|--------|
| jszbcg | 江苏招标采购服务平台 | REST API + PDF→MD |
| yancheng_gov | 盐城市政府采购网 | HTML 详情页 |
| ycggzy | 盐城市公共资源交易平台 | REST API（SPA） |
| sufu | 苏服务 | REST API |
| yueda | 悦达集团阳光采购平台 | HTML 详情页 |
| dongfang | 盐东方产业投资集团有限公司 | HTML 详情页 |
| jscn | 江苏世纪新城投资控股集团有限公司 | HTML 详情页 |
| dushi | 盐城市都市建设投资集团有限公司 | HTML 详情页 |
| chennan | 江苏省盐南高新区公共资源交易电子化服务平台 | HTML 详情页 |
| kaifaqu | 盐城经济技术开发区行政审批局公共资源交易服务平台 | HTML 详情页 |
| bigdata | 盐城市大数据集团 | HTML 详情页 |
| jingkai | 盐城经开城市发展投资集团有限公司 | HTML 详情页 |

## 数据质量（2026-06-23）

### unified.db 三表（jszbcg 全年历史补采后）

| 表 | 总数 | 发包方 | 金额 | 开标时间 |
|----|------|--------|------|--------|
| tender（招标公告） | 3714 | 88% | 78% | 90% |
| award（中标成交） | 3634 | 92% | 74% | — |
| intention（采购意向） | 974 | 98% | 53% | — |

| 字段 | 说明 |
|------|------|
| purchaser（发包单位） | 整体 90%，v2.0 清洗了 155 条脏数据 |
| std_district（行政区划） | ~98% |
| std_category（项目分类） | 42%，规则持续扩充 |

## 目录结构

```
crawlers/
  base.py                 DB 基类（SiteDB + BaseCrawler）
  html_common.py          HTML 站通用工具（get_html / save_page_md / infer_notice_type）
  jszbcg.py               江苏招标采购（API + 爬取时下载 PDF）
  ycggzy.py               盐城公共资源交易（SPA API）
  yancheng_gov.py         盐城政府采购网
  sufu.py                 苏服采（纯 API）
  yueda.py / dongfang.py / jscn.py / dushi.py
  chennan_kaifaqu.py      盐南高新区 + 开发区（共用爬虫）
  bigdata.py / jingkai.py

enrich_details.py         详情页富化（统一读本地 page_path MD，jszbcg 同上）
add_std_district.py       行政区划打标（std_district）
add_std_category.py       项目分类打标（proj_major_cat / proj_minor_cat）
build_unified.py          合并 12 个 DB → data/unified.db
export_excel.py           导出 Excel
run_collection.py         采集入口（支持 --days / --site）
run_daily.sh              每日全流程脚本（凌晨 2 点）

generate_tender_report.py       盐开招标公告月报（PDF）
generate_countdown_report_pdf.py 盐开开标倒计时报告（PDF）
generate_countdown_report.py    盐开开标倒计时报告（Excel 备用）

download_jszbcg_pdfs.py        jszbcg PDF 历史批量下载（初始化用）
download_site_pages.py         HTML 站详情页历史批量下载（初始化用）
rename_pages.py                按项目名重命名 MD 缓存文件
reenrich_ycggzy.py             ycggzy 专项补采（发包单位从列表 API 回填）
cleanup_art_20171_dupes.py     清理 yancheng_gov art_20171 脏数据（默认dry-run）

# yancheng_gov 专项工具（Playwright，按需运行）
enrich_yancheng_gov.py         yancheng_gov 完整补全（Playwright + 表格专项解析）
enrich_yancheng_gov_playwright.py  yancheng_gov 轻量补全（只处理 detail_fetched=2 的记录）

# 调试 / 历史工具（不属于生产流程）
dry_run_v2.py                  分类规则调试（只读，不写 DB）
fix_titles.py                  修复 yancheng_gov 乱码标题（一次性，已用完）
migrate_from_old.py            从旧 history.db 迁移数据（一次性，已用完）

data/
  *.db                    各站点独立 SQLite 数据库
  unified.db              合并后三张表（tender / award / intention）
  pdfs/jszbcg/            jszbcg 本地 PDF 缓存（~1300 个，616MB）
  pages/{site}/           各站详情页本地 MD 缓存（~1130 个）

output/                   导出的 Excel / PDF 文件
logs/                     运行日志
```

## 本地缓存架构

v1.4 起，所有富化操作均基于本地 MD 文件，重跑无需联网：

- **jszbcg**：爬虫采集新记录时立即下载 PDF → 转 MD → `data/pages/jszbcg/{项目名}.md`；富化直接读 MD
- **HTML 站**：爬虫采集详情页时同步保存 Markdown → `data/pages/{site}/{项目名}.md`，富化直接读本地
- **enrich_details.py**：统一读 `page_path` 本地 MD；首次拉取后自动缓存
- **sufu**：纯 API，无需页面；**ycggzy**：数据在列表 API 的 raw_json，无需详情页

## 依赖安装

```bash
pip install requests beautifulsoup4 lxml pymupdf paddleocr openpyxl html2text reportlab
```

> PaddleOCR 首次运行会自动下载模型（约 100MB）

## 运行流程

### 日常增量（推荐）

```bash
# 1. 采集（同步下载 PDF / HTML 页面）
python3 run_collection.py --days 3

# 2. 富化（读本地 MD 缓存，离线运行；jszbcg 已在步骤1 PDF→MD）
python3 enrich_details.py

# 3. 打标 + 合并
python3 add_std_district.py
python3 add_std_category.py
python3 build_unified.py

# 4. 生成报告
python3 generate_tender_report.py          # 盐开月报
python3 generate_countdown_report_pdf.py   # 盐开开标倒计时

# 5. 导出 Excel（可选）
python3 export_excel.py
```

### 首次初始化（历史数据补全缓存）

```bash
# 下载所有 HTML 详情页（断点续传）
python3 download_site_pages.py

# 下载所有 jszbcg PDF（断点续传）
python3 download_jszbcg_pdfs.py
```

### 单站点操作

```bash
# 只采集某个站点
python3 run_collection.py --days 7 --site jscn

# 只富化某个站点
python3 -c "from enrich_details import enrich_site; enrich_site('jscn')"
```

### yancheng_gov Playwright 补全（WAF 绕过，按需）

```bash
# 轻量版（只处理 detail_fetched=2 的记录）
python3 enrich_yancheng_gov_playwright.py

# 完整版（含表格专项解析，补全率更高）
python3 enrich_yancheng_gov.py
```

### ycggzy 补采

```bash
# ycggzy 是 SPA，purchaser 来自列表 API，不走 enrich_details
python3 reenrich_ycggzy.py --start 2026-05-01 --end 2026-06-22
```

## 分类体系

`proj_major_cat` / `proj_minor_cat` 两级分类，反向过滤策略：
先标注不相关类别（物业/市政/法律/劳务/车辆/设计等），未标注的即为信息化商机池。

规则文件：`add_std_category.py`（RULES 列表）

## 已知限制

- **sufu 中标单位 100% 空**：平台详情 API 需登录，无法获取
- **yueda 预算 97% 空**：网站公告页本身不披露预算金额
- **ycggzy**：SPA 页面，数据来自列表 API 的 `raw_json`，不走 HTML 富化
- **bigdata**：静态页面仅展示最近 10 页，无法回溯历史

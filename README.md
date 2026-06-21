# 盐城市全域招标信息采集系统 Pro

盐城市 12 个招标网站的数据采集、富化、分类和导出系统。

**当前版本**：v1.3 | **数据量**：3920 条原始记录 | **最后更新**：2026-06-21

## 覆盖站点（12个）

| 站点 | 说明 | 采集方式 |
|------|------|--------|
| jszbcg | 江苏招标采购服务平台（盐城） | REST API + PDF OCR |
| yancheng_gov | 盐城政府采购网 | HTML 详情页 |
| ycggzy | 盐城公共资源交易平台 | REST API（SPA） |
| sufu | 苏服采 | REST API |
| yueda | 悦达阳光采购平台 | HTML 详情页 |
| dongfang | 东方新锐招标 | HTML 详情页 |
| jscn | 江苏世纪新城 | HTML 详情页 |
| dushi | 都市建设投资 | HTML 详情页 |
| chennan | 盐南高新区交易网 | HTML 详情页 |
| kaifaqu | 盐城开发区交易网 | HTML 详情页 |
| bigdata | 大数据产业集团 | HTML 详情页 |
| jingkai | 盐城经开区城发 | HTML 详情页 |

## 数据质量（2026-06-21）

| 字段 | 填充数 | 填充率 |
|------|--------|--------|
| purchaser（发包单位） | 3130 / 3920 | 80% |
| budget（预算金额） | 1538 / 3920 | 39% |
| open_date（开标时间） | 1133 / 3920 | 29% |
| winner（中标单位） | 1230 / 3920 | 31% |
| std_district（行政区划） | ~98% | — |
| std_category（项目分类） | 33% | 规则持续扩充 |

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

enrich_details.py         HTML 详情页富化（优先读本地 MD 缓存）
enrich_jszbcg_ocr.py      PDF OCR 富化（优先读本地 PDF 缓存）
add_std_district.py       行政区划打标（std_district）
add_std_category.py       项目分类打标（proj_major_cat / proj_minor_cat）
build_unified.py          合并 12 个 DB → data/unified.db
export_excel.py           导出 Excel
run_collection.py         采集入口（支持 --days / --site）
run_daily.sh              每日全流程脚本（凌晨 2 点）

download_jszbcg_pdfs.py   jszbcg PDF 历史批量下载（初始化用）
download_site_pages.py    HTML 站详情页历史批量下载（初始化用）
rename_pages.py           按项目名重命名 MD 缓存文件

data/
  *.db                    各站点独立 SQLite 数据库
  unified.db              合并后三张表（tender / award / intention）
  pdfs/jszbcg/            jszbcg 本地 PDF 缓存（~1300 个，616MB）
  pages/{site}/           各站详情页本地 MD 缓存（~1130 个）

output/                   导出的 Excel 文件
logs/                     运行日志
```

## 本地缓存架构

v1.3 起，所有富化操作均基于本地文件，重跑无需联网：

- **jszbcg**：爬虫采集新记录时立即下载 PDF → `data/pdfs/jszbcg/{bulletinID}.pdf`
- **HTML 站**：爬虫采集详情页时同步保存 Markdown → `data/pages/{site}/{项目名}.md`
- **enrich_details.py**：优先读 `page_path` 本地 MD；首次拉取后自动缓存
- **enrich_jszbcg_ocr.py**：优先读 `pdf_path` 本地 PDF；首次下载后自动缓存

## 依赖安装

```bash
pip install requests beautifulsoup4 lxml pymupdf paddleocr openpyxl html2text
```

> PaddleOCR 首次运行会自动下载模型（约 100MB）

## 运行流程

### 日常增量（推荐）

```bash
# 1. 采集（同步下载 PDF / HTML 页面）
python3 run_collection.py --days 3

# 2. 富化（读本地缓存，离线运行）
python3 enrich_details.py
python3 enrich_jszbcg_ocr.py

# 3. 打标 + 合并
python3 add_std_district.py
python3 add_std_category.py
python3 build_unified.py

# 4. 导出 Excel
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

## 分类体系

`proj_major_cat` / `proj_minor_cat` 两级分类，反向过滤策略：
先标注不相关类别（物业/市政/法律/劳务/车辆/设计等），未标注的即为信息化商机池。

规则文件：`add_std_category.py`（RULES 列表）

## 已知限制

- **sufu 中标单位 100% 空**：平台详情 API 需登录，无法获取
- **yueda 预算 97% 空**：网站公告页不披露预算金额
- **ycggzy**：SPA 页面，数据来自列表 API 的 `raw_json`，不走 HTML 富化

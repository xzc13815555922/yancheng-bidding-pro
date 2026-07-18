# yancheng-bidding-pro 数据字典

> **版本**：v1.0  
> **生成日期**：2026-07-18  
> **审计依据**：GB/T 36073-2018《数据管理能力成熟度评估模型》(DCMM) 第 7 数据架构域  
> **生成方式**：通过 PRAGMA table_info 自动抽取 + 业务注释手写

---

## 一、数据源总览

本项目数据来自 13 个采集源（12 站点 + 1 天眼查运营商）。

| site_key | 中文名 | 存储 DB | 业务定位 |
|----------|--------|---------|----------|
| jszbcg | 江苏招标采购服务平台 | `data/jszbcg.db` | 主招标源（PDF+MD） |
| yancheng_gov | 盐城市政府采购网 | `data/yancheng_gov.db` | 政府采购主源 |
| ycggzy | 盐城公共资源交易 | `data/ycggzy.db` | 公共资源主源（SPA） |
| sufu | 苏服务 | `data/sufu.db` | 苏服采（API） |
| yueda | 悦达集团 | `data/yueda.db` | 悦达阳光采购 |
| dushi | 都市建设投资集团 | `data/dushi.db` | 盐城本地国企 |
| jscn | 世纪新城 | `data/jscn.db` | 盐城本地国企 |
| chennan | 盐南高新区 | `data/chennan.db` | 盐南区平台 |
| dongfang | 盐东方 | `data/dongfang.db` | 盐城本地国企 |
| bigdata | 大数据集团 | `data/bigdata.db` | 盐城本地国企 |
| jingkai | 经开城发 | `data/jingkai.db` | 盐城经开区 |
| kaifaqu | 经开区行政审批 | `data/kaifaqu.db` | 盐城经开区 |
| tyc | 天眼查运营商 | `data/tyc.db` | 运营商中标（Playwright） |

每站独立 DB 后，归一化到 **`data/unified.db`**，由 `build_unified.py` 写入。

---

## 二、站点 DB Schema（每站独立）

每站 `notices` 表共用统一 schema（由 `crawlers/base.py:SiteDB` 维护）：

| 字段 | 类型 | 必填 | 业务含义 | 数据来源 |
|------|------|------|----------|----------|
| `id` | TEXT | 主键 | 业务主键（`make_id(site, detail_url)` 生成） | 自动生成 |
| `site` | TEXT | 是 | 站点 key（来自 config.SITES） | 自动填充 |
| `site_name` | TEXT | 是 | 站点中文名（来自 config.SITE_NAMES） | 自动填充 |
| `notice_type` | TEXT | 是 | 公告类型：`tender` / `award` / `intention` / `other` | 采集器分类 |
| `notice_type_raw` | TEXT | 否 | 站点原始类型（如"招标公告"） | 原始 API |
| `notice_subtype` | TEXT | 否 | other 表细分（流标/终止/更正/合同） | 解析器 |
| `title` | TEXT | 否 | 公告标题（原始） | 原始 API |
| `project_name` | TEXT | 否 | 项目名称（解析后） | 解析器 |
| `purchaser` | TEXT | 否 | 采购人/招标人 | 解析器 |
| `agency` | TEXT | 否 | 代理机构 | 解析器 |
| `winner` | TEXT | 否 | 中标人（仅 award） | 解析器 |
| `budget` | REAL | 否 | 预算金额（元） | 解析器（统一单位） |
| `winning_amount` | REAL | 否 | 中标金额（元，仅 award） | 解析器 |
| `open_date` | TEXT | 否 | 开标时间（tender） | 解析器 |
| `deadline` | TEXT | 否 | 报名截止时间 | 解析器 |
| `publish_date` | TEXT | 否 | 发布日期 | 原始 API |
| `detail_url` | TEXT | 否 | 详情页 URL（UNIQUE 白名单 3 站） | 原始 API |
| `page_path` | TEXT | 否 | 本地缓存 MD 路径 | download_site_pages.py |
| `pdf_path` | TEXT | 否 | 本地 PDF 路径（仅 jszbcg） | download_jszbcg_pdfs.py |
| `content` | TEXT | 否 | 详情页正文（ycggzy 等 SPA） | 原始 API |
| `raw_json` | TEXT | 否 | 原始 API 响应（JSON 字符串） | 原始 API |
| `section` | TEXT | 否 | ycggzy classCode 映射（"工程建设"等） | repair_derived_fields |
| `std_district` | TEXT | 否 | 标准化区县（"盐南高新区"等） | add_std_district.py |
| `proj_major_cat` | TEXT | 否 | 标准化大类别（"工程"/"货物"/"服务"） | add_std_category.py |
| `proj_minor_cat` | TEXT | 否 | 标准化子类别（"信息化工程"等） | add_std_category.py |
| `sme_target` | TEXT | 否 | 中小微企业标签：`sme_specific` / `sme_preference` / `none` | extract_sme_target.py |
| `created_at` | TEXT | 否 | 入库时间戳 | 自动填充 |
| `updated_at` | TEXT | 否 | 最后更新时间戳 | 自动填充 |

**索引**：
- `idx_notices_detail_url`（白名单 3 站：jszbcg / yancheng_gov / tyc） — 防重复入库
- 其他站无 UNIQUE INDEX（因允许同 detail_url 跨日变更）

---

## 三、unified.db Schema（核心业务表）

### 3.1 `tender` 表 — 招标公告

| 字段 | 类型 | 来源 | 备注 |
|------|------|------|------|
| `id` | TEXT | notices.id | 主键 |
| `site_name` | TEXT | notices.site_name | 来源站点 |
| `std_district` | TEXT | notices.std_district | 标准化区县 |
| `proj_major_cat` | TEXT | notices.proj_major_cat | 标准化大类别 |
| `proj_minor_cat` | TEXT | notices.proj_minor_cat | 标准化子类别 |
| `publish_date` | TEXT | notices.publish_date | 发布日期 |
| `project_name` | TEXT | notices.project_name | 项目名 |
| `purchaser` | TEXT | notices.purchaser | 采购人 |
| `budget` | REAL | notices.budget | 预算（元） |
| `open_date` | TEXT | notices.open_date | 开标时间 |
| `deadline` | TEXT | notices.deadline | 报名截止 |
| `detail_url` | TEXT | notices.detail_url | 详情 URL |
| `sme_target` | TEXT | notices.sme_target | 中小微标签 |

**记录数**：4352（2026-07-18）

### 3.2 `award` 表 — 中标/成交

| 字段 | 类型 | 来源 | 备注 |
|------|------|------|------|
| `id` | TEXT | notices.id | 主键 |
| `site_name` | TEXT | notices.site_name | - |
| `std_district` | TEXT | notices.std_district | - |
| `proj_major_cat` | TEXT | notices.proj_major_cat | - |
| `proj_minor_cat` | TEXT | notices.proj_minor_cat | - |
| `publish_date` | TEXT | notices.publish_date | - |
| `project_name` | TEXT | notices.project_name | - |
| `purchaser` | TEXT | notices.purchaser | - |
| `winner` | TEXT | notices.winner | 中标人 |
| `winning_amount` | REAL | notices.winning_amount | 中标金额 |
| `detail_url` | TEXT | notices.detail_url | - |

**记录数**：4961

### 3.3 `intention` 表 — 采购意向

| 字段 | 类型 | 来源 | 备注 |
|------|------|------|------|
| `id` | TEXT | notices.id | - |
| `site_name` | TEXT | notices.site_name | - |
| `std_district` | TEXT | notices.std_district | - |
| `proj_major_cat` | TEXT | notices.proj_major_cat | - |
| `proj_minor_cat` | TEXT | notices.proj_minor_cat | - |
| `publish_date` | TEXT | notices.publish_date | - |
| `project_name` | TEXT | notices.project_name | **真项目名（v2.7+）** |
| `purchaser` | TEXT | notices.purchaser | - |
| `budget` | REAL | notices.budget | - |
| `expected_list` | TEXT | notices.expected_list | JSON 列表（v2.7+） |
| `detail_url` | TEXT | notices.detail_url | - |
| `sme_target` | TEXT | notices.sme_target | - |

**记录数**：1286

### 3.4 `other` 表 — 流标/终止/更正/合同

| 字段 | 类型 | 来源 | 备注 |
|------|------|------|------|
| `id` | TEXT | notices.id | - |
| `site_name` | TEXT | notices.site_name | - |
| `notice_subtype` | TEXT | notices.notice_subtype | 细分类型 |
| `std_district` | TEXT | notices.std_district | - |
| `proj_major_cat` | TEXT | notices.proj_major_cat | - |
| `proj_minor_cat` | TEXT | notices.proj_minor_cat | - |
| `publish_date` | TEXT | notices.publish_date | - |
| `project_name` | TEXT | notices.project_name | - |
| `purchaser` | TEXT | notices.purchaser | - |
| `detail_url` | TEXT | notices.detail_url | - |

**记录数**：3866

### 3.5 `project_links` 表 — 关联关系

| 字段 | 类型 | 备注 |
|------|------|------|
| `tender_id` | TEXT | 关联 tender.id |
| `award_id` | TEXT | 关联 award.id |
| `canonical_name` | TEXT | 标准化项目名 |
| `match_type` | TEXT | exact / fuzzy / manual |
| `amendment_count` | INTEGER | 该链路中更正公告次数（默认 0） |

**记录数**：3119（关联率 67.2%）

---

## 四、关键枚举值定义

### 4.1 `notice_type` 枚举

| 值 | 中文 | 业务范围 |
|----|------|----------|
| `tender` | 招标公告 | 公开招标 / 邀请招标 |
| `award` | 中标/成交 | 中标公示 / 成交结果 |
| `intention` | 采购意向 | 政府采购意向公开 |
| `other` | 其他 | 流标 / 终止 / 更正 / 合同 |

### 4.2 `notice_subtype` 枚举（other 表细分）

| 值 | 中文 |
|----|------|
| `flow` | 流标 |
| `terminate` | 终止 |
| `amendment` | 更正公告 |
| `contract` | 合同公告 |
| `unknown` | 未分类 |

### 4.3 `sme_target` 枚举

| 值 | 含义 | 报表颜色 |
|----|------|----------|
| `sme_specific` | 专门面向中小微企业 | 🟢 绿 |
| `sme_preference` | 优惠中小微企业 | 🟠 橙 |
| `none` / NULL | 无 | ⚪ 默认 |

---

## 五、数据质量基线（`config.SITE_BASELINES`）

> 详见 `config.py`。当前为 2026-07-18 治标调整版（8 项 TBD_T 标记待治本）。

### 5.1 unified 表基线（`UNIFIED_BASELINES`）

| 表 | 基线（条） | 实测（2026-07-18） |
|----|-----------|-------------------|
| `tender` | 1300 | 4352 ✅ |
| `award` | 1300 | 4961 ✅ |
| `intention` | 1000 | 1286 ✅ |
| `other` | 1500 | 3866 ✅ |

### 5.2 站点字段基线（节选）

详见 `config.py SITE_BASELINES`，每项含 `count / purchaser / budget / open_date / winner / winning_amount` 阈值。

---

## 六、采集器注册表（`config.CRAWLERS`）

13 个采集器定义：
```python
CRAWLERS = [
    ("jszbcg",       "crawlers.jszbcg",          "JSZbcgCrawlerPro"),
    ("yancheng_gov", "crawlers.yancheng_gov",    "YanchengGovCrawlerPro"),
    ("ycggzy",       "crawlers.ycggzy",          "YcggzyCrawlerPro"),
    ("bigdata",      "crawlers.bigdata",         "BigdataCrawlerPro"),
    ("jingkai",      "crawlers.jingkai",         "JingkaiCrawlerPro"),
    ("kaifaqu",      "crawlers.chennan_kaifaqu", "KaifaquCrawlerPro"),
    ("chennan",      "crawlers.chennan_kaifaqu", "ChengnanCrawlerPro"),
    ("dongfang",     "crawlers.dongfang",        "DongfangCrawlerPro"),
    ("dushi",        "crawlers.dushi",           "DushiCrawlerPro"),
    ("jscn",         "crawlers.jscn",            "JscnCrawlerPro"),
    ("yueda",        "crawlers.yueda",           "YuedaCrawlerPro"),
    ("sufu",         "crawlers.sufu",            "SufuCrawlerPro"),
    ("tyc",          "crawlers.tyc_crawler",     "TYCCrawlerPro"),
]
```

---

## 七、数据血缘（Data Lineage）

```
13 站点 API/HTML
    ↓ (各 crawlers/*.py)
13 站点独立 DB (.db)
    ↓ (download_site_pages.py / download_jszbcg_pdfs.py)
data/pages/{site}/*.md  (本地 MD 缓存)
    ↓ (enrich_details.py / enrich_yancheng_gov.py 等)
13 站点 DB (字段填充)
    ↓ (add_std_district.py / add_std_category.py / extract_sme_target.py)
13 站点 DB (标准化字段)
    ↓ (build_unified.py)
unified.db (4 表 + project_links + audit 表 - 待加)
    ↓ (verify_quality.py)
质量门验证
    ↓ (4 份 PDF 生成脚本)
output/*.pdf
    ↓ (push-pdfs.sh v3.0, openclaw cron f605317e)
飞书群 oc_922159a1e552ff69e99a99c1bd4d598b
```

---

## 八、变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-18 | v1.0 | 初始版本（审计批号 小标-2026-07-18-数据治理 P0-存-1） |

---

**维护者**：执行员小标  
**下次审查**：随数据 schema 变更同步更新

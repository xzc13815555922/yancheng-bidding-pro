# 盐城市全域招标信息采集系统 Pro

盐城市 12 个招标网站的数据采集、富化、分类和报告生成系统。

**当前版本**：v2.6 | **数据量**：12739条原始 → unified.db 四表合计 12129 | **最后更新**：2026-06-30

> **v2.6 变更说明（2026-06-26）**：① unified.db 新增第四张表 `other`（流标/终止/更正/合同，3031条）及 `project_links` 关联表（tender×award，2652条68%覆盖），新增 `project_chain` 视图 ② `enrich_details.py` 解耦（1082→829行，per-site 解析器迁到 `crawlers/jszbcg_parser.py` / `crawlers/sufu_parser.py`，测试迁到 `tests/`）③ `enrich_amendment_opendate.py` 新增 jszbcg `【更正公告】` 前缀剥离 ④ 新增 `reenrich.py`（补全统一入口）、`report_failed_bids.py`（流标报告）、`expand_intention.py`（批次意向展开）。

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

## 数据质量（2026-06-30 v2.6）

### unified.db 四表

| 表 | 总数 | 发包方 | 金额 | 开标时间 |
|----|------|--------|------|--------|
| tender（招标公告） | 3802 | 90% | 81% | 90% |
| award（中标成交） | 4035 | 92% | 75% | — |
| intention（采购意向） | 1143 | 98% | 99% | — |
| other（流标/终止/更正/合同） | 3149 | — | — | — |

| 表/字段 | 覆盖率 | 说明 |
|---------|--------|------|
| award.winner | 87% | sufu 结构性0%（SPA 需登录） |
| project_links | 67% | tender×award 关联（2723条），project_chain 视图 |
| std_district | ~98% | 区县标准化 |
| std_category | ~42% | YAML 规则库，持续扩充 |

## 目录结构

```
crawlers/
  base.py                 DB 基类（SiteDB + BaseCrawler）
  html_common.py          HTML 站通用工具（parse_datetime / infer_notice_type / classify_other_subtype）
  jszbcg_parser.py        jszbcg raw_json 字段映射（v2.6 从 enrich_details 解耦）
  sufu_parser.py          sufu raw_json 字段映射（v2.6 从 enrich_details 解耦）
  jszbcg.py               江苏招标采购（API + 爬取时下载 PDF）
  ycggzy.py               盐城公共资源交易（SPA API）
  yancheng_gov.py         盐城政府采购网
  sufu.py                 苏服采（纯 API）
  yueda.py / dongfang.py / jscn.py / dushi.py
  chennan_kaifaqu.py      盐南高新区 + 开发区（共用爬虫）
  bigdata.py / jingkai.py
  tyc_crawler.py          天眼查运营商中标数据采集（Playwright，按月手动运行）
  tyc_login.py            天眼查登录 + Cookie 更新工具

tests/
  test_enrich_details.py  enrich_details 单测（6项，关键词覆盖验证）

enrich_details.py         详情页富化（v2.6 解耦，1082→829行）
reenrich.py               补全统一入口（details/yancheng_gov/ocr/amendment 四步）
enrich_amendment_opendate.py  更正公告 open_date 联动（支持 suffix + 【前缀】剥离）
expand_intention.py       yancheng_gov 批次意向展开（表格→expected_list JSON）

add_std_district.py       行政区划打标（std_district）
add_std_category.py       项目分类打标（proj_major_cat / proj_minor_cat）
build_unified.py          合并 12 个 DB → unified.db（四表 + project_links，v2.6）
build_project_links.py    tender×award 关联表（project_chain 视图，--report 模式）
export_excel.py           导出 Excel（按需手动）
run_collection.py         采集入口（支持 --days / --site）

report_failed_bids.py     流标/终止 5 维度报告（--site/--start/--end/--csv）

generate_tender_report.py            盐开招标公告月报（PDF）
generate_countdown_report_pdf.py     盐开开标倒计时报告（PDF）
generate_countdown_report.py         盐开开标倒计时报告（Excel 备用）
generate_operator_award_report.py    运营商月度中标报告（PDF，单站点）
generate_operator_combined_report.py 运营商综合月报（PDF，三源合并：ybp+tyc+obm）

rules/
  category.yaml           分类规则（48条，YAML 格式，v2.5）

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
  unified.db              四张表（tender/award/intention/other）+ project_links + project_chain 视图
  tyc.db                  天眼查运营商中标数据（bids 表）
  pdfs/jszbcg/            jszbcg 本地 PDF 缓存（~1800 个）
  pages/{site}/           各站详情页本地 MD 缓存（~3000 个）

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

### 运营商综合月报（三源合并，每月手动）

```bash
# 生成运营商综合月报 PDF（ybp + tyc + obm 三源合并）
python3 generate_operator_combined_report.py --month 2026-06

# 仅生成单站点运营商中标报告
python3 generate_operator_award_report.py --month 2026-06
```

### 天眼查运营商数据采集（每日自动 + Cookie 失效时手动）

```bash
# 首次或 Cookie 过期时重新登录（Playwright，会保存 data/cookies.json）
python3 crawlers/tyc_login.py

# 采集运营商中标数据（写入 data/tyc.db）— 每天 05:00 cron 自动跑
python3 crawlers/tyc_crawler.py --days 1

# 仅验证 Cookie 有效性（不会测试招投标会员权限）
python3 crawlers/tyc_login.py --verify-only
```

> **重要**：`--days 1` 仅取近 1 天数据，因为数据已存在 DB，去重后基本不增加新记录但提前停止翻页（45分钟 → 4分钟）。
> 天眼查招投标数据需会员权限（有效期至 2028 年）。Cookie 服务端失效无法从 Cookie 时间戳判断，建议每月手动登录一次。

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

---

## 修复清单（v2.2 → v2.3，2026-06-25）

### 修复 #92：05:00 cron stall timeout 问题

| 项目 | 说明 |
|------|------|
| 问题 | cron 用 `agentTurn` 模式调度 9 步 Python 脚本，agent 调用 exec 后长时间无新 model call，系统判定 stall，10 分钟后强制 timeout |
| 修复 | 新增 `run-full-pipeline.sh` bash 脚本（10 步独立脚本），cron payload 改为只调一行 `bash run-full-pipeline.sh` |
| 文件 | `run-full-pipeline.sh`（新增） |
| 验证 | 手动跑 4 分钟完成全部 10 步（含天眼查 + 12站采集 + 3 份 PDF + Excel） |
| cron 变化 | 任务名改为 `yancheng-bidding-pro daily 5:00 full pipeline`，timeout 1800s → 3600s |

### 修复 #93：tyc_crawler 提速 10 倍（45min → 4min）

| 项目 | 说明 |
|------|------|
| 问题 | `crawlers/tyc_crawler.py` 默认不传 `--days`，每家运营商翻满 `MAX_PAGES=20` 页（×13 家=45 分钟） |
| 根因 | cron 已设置每天跑一次，DB 里已有数据。采集器仍然全量翻页是浪费 |
| 修复 | `run-full-pipeline.sh` 调用时加 `--days 1`，第 1 页检测到超出窗口立即停止翻页 |
| 文件 | `run-full-pipeline.sh` 第 2 步调用方式 |
| 验证 | 13 家运营商 4 分钟跑完，新增 0 条（已去重），2 条盐城 MD 已入库 |

### 修复 #94：取消 Excel 推送（同步三处）

| 项目 | 说明 |
|------|------|
| 问题 | SKILL.md 历史定义了 Excel 输出，08:30 推送 cron 也推了 Excel，但用户实际只需要 3 份 PDF |
| 修复 | 同步修改三处：① `SKILL.md` outputs 移除 excel、加⚠️ 说明 ② `run-full-pipeline.sh` 移除 `export_excel.py` 步骤 ③ 08:30 推送 cron 移除 Excel 推送 |
| 文件 | `SKILL.md`、`run-full-pipeline.sh`、cron job `f605317e-bb5c-4a0d-b605-efdc31a609b4` |
| 说明 | `export_excel.py` 脚本保留，需要时手动运行即可，不进生产流程 |

### 修复 #95：P0-1 修复 — pipeline 补 download_site_pages.py（顺手修 import re 隐藏 bug）

| 项目 | 说明 |
|------|------|
| 问题 | `run-full-pipeline.sh` 漏掉 `download_site_pages.py` 步骤；新采 HTML 站详情页永远无 page_path，富化无米下锅 |
| 隐藏 bug | `download_site_pages.py` 缺 `import re`，脚本从未成功跑过！解释了为什么 sufu/ycggzy page_path 历史为 0% |
| 修复 | ① `run-full-pipeline.sh` 加 Step 2.5 `download_site_pages.py` ② `download_site_pages.py` 加 `import re` |
| 验证 | 新 3 天数据 page_path 比例从 38.8% → 77.0%（+222 条），sufu 从 0/419 → 415/419（+415 条） |

### 修复 #96：B 短期 — 月报/倒计时报告加红字警告（jszbcg open_date 字段语义错误）

| 项目 | 说明 |
|------|------|
| 问题 | 阿明审计发现 jszbcg 站 `open_date` 实际用的是 `openBidTime`（发布时间），代码注释里也说了。1881 条"开标时间"全部失真。CEO 关注的"开标倒计时报告"直接受影响 |
| 短期修复 | ① `generate_tender_report.py` 首页加红字警告 `⚠️ 警告：jszbcg 站的"开标时间"字段实际为招标公告的发布时间，并非真实开标时间。长期修复中（月底）。` ② `generate_countdown_report_pdf.py` 同上 |
| 长期修复 | **#97 已修复**：见下文 |
| 文件 | `generate_tender_report.py`、`generate_countdown_report_pdf.py` |

### 修复 #97：B 长期 — jszbcg 真开标时间解析（核心修复）

| 项目 | 说明 |
|------|------|
| 问题 | jszbcg 站 `crawlers/jszbcg.py:262` 用 `openBidTime` 写 open_date，实际是发布时间。1881 条全部失真 |
| 修复 | 新建 `reenrich_jszbcg_open_date.py`：读 page_path MD，正则解析 4 类格式（开标时间/文件开启时间/开启时间/开标日期）；支持 OCR 空格格式（2026 年 07 月 03 日 15 时 00 分） |
| 验证 | 候选 1710 条，命中 1690（99.4%），写入 DB 1683 条；合理性 99.9% open_date >= publish_date |
| 同步 | 移除月报/倒计时报告红字警告（字段已修复） |
| 文件 | `reenrich_jszbcg_open_date.py`（新增 156 行）、`generate_tender_report.py`（去警告）、`generate_countdown_report_pdf.py`（去警告） |
| git commit | `d1c46ab` |

### 修复 #98：C — ycggzy 改 1 行 + 补救脚本

| 项目 | 说明 |
|------|------|
| 问题 | `crawlers/ycggzy.py:611` 显式 `if k != "content"` 排除 content，富化机会只有一次，漏抓无补救 |
| 修复 | ① 改 `crawlers/ycggzy.py:611` 改成 `json.dumps(item)` 保留 content ② 新建 `reenrich_ycggzy_from_list_api.py`（270 行）补救 4050 条历史 |
| 验证 | 命中 code 2342/2373 (98.7%)，解析 2336，DB 写入 1810；4 关键字段填充率：winning_amount 0→30.0%、deadline 0→21.7%、budget_unit 0→42.8%、budget_text 0→42.8% |
| 关键 | `raw_json.content` 永久修复，未来可二富化 |
| git commit | `cfb89ad` |

### 修复 #99-#103：富化层 5 个关键词/排除词补齐

| # | 修复 | 关键数据 | git commit |
|---|------|---------|-----------|
| 99 | P1-4 `_ORG_SUFFIX` 扩 12+ 后缀（中学/联合会/党委/村委等） | yancheng_gov purchaser +41 条（96.8%→98.3%）| `a11185b` |
| 100 | P1-5 `WINNER_KEYWORDS` 加"供应商名称"等 5 个表格列名 | award winner 99.1%→99.3%（+1 条历史，未来关键） | `5a5b0f6` |
| 101 | P1-6 `BUDGET_KEYWORDS` 补"采购预算(万元)"等 7 个带括号单位变种 + 表格 fallback 逻辑 | yancheng_gov budget +43 条（28.6%→30.2%） | `3a8f954` |
| 102 | P1-7 `BUDGET_EXCLUDE` 加"代理费/服务费"等 16 个排除词 | 清理 80 条 award 类误匹配（85→5 条），全站 budget 27.2%（健康值） | `2e51c17` |
| 103 | P2-1 `OPEN_DATE_KEYWORDS` 加"截止时间、开标时间和地点"等 5 个合并标题 | yancheng_gov open_date +31 条（23.5%→24.7%）| `e8d00cb` |

### 修复 #104：v2.4 文档同步

- README.md：本节补充 v2.3→v2.4 全部 8 个修复记录（#97-#103）
- SKILL.md：同步 v2.3 → v2.4 版本号 + 修复清单

### 修复 #105：P2-3 — budget 关键词'采购预算' + 空白 + '(万元)' 拆分型匹配

| 项目 | 说明 |
|------|------|
| 问题 | yancheng_gov 意向公告表格拆分型'采购预算  \n(万元) | 500'，P1-6 re.escape(kw) 要求连续 100% 漏采；抽样 30 条 23/23 拆分型全军覆没 |
| 修复 | enrich_details.py BUDGET 处理段 P1-6 fallback 改用拆解模式: 基础词+任意空白+(单位)+任意字符(非贪婪)+数字；同时修'if (\' in kw'只匹配英文括号 bug |
| 验证 | yancheng_gov budget +19 条 (P1-6 未采到的拆分型)；单测 _test_budget_kw_split() 4 个 case 全过 |
| 文件 | enrich_details.py (+45/-4) |
| git commit | `3b57baa` |

### 修复 #106：P2-4 — add_std_district.py CODE_MAP 错标（320903=盐南→盐都）

| 项目 | 说明 |
|------|------|
| 问题 | add_std_district.py:25 误把 district_code=320903 标'盐南'。ycggzy 爬虫 _area_to_region 映射 320903='盐都区'。导致 256 条 ycggzy+ 干提记录被误归盐南, 盐南虚高 |
| 修复 | ① 320903 '盐南'→'盐都' ② 新增 320971='盐南' (ycggzy API 实际用此代码) ③ 保留 320992='盐南' (历史兼容) |
| 验证 | ycggzy '盐南' 256→43 条 (213 归到盐都); yancheng_gov 同步修复; intention report 清单 1: 7→6 (少 1 条大冈镇错标), 清单 2 候选: 57→40 (少 17 条盐都混入) |
| 备份 | data/backup/ycggzy.bak-20260625-P24, data/backup/yancheng_gov.bak-20260625-P24 |
| 文件 | add_std_district.py (+6/-1) |
| git commit | (待提交) |

---

## v2.4 累计效果一览

| 维度 | 修复前 | 修复后 |
|------|-------|-------|
| 新采数据 page_path | 38.8% | 77.0% |
| sufu page_path | 0 | 99.0% |
| jszbcg open_date 真实率 | 0% | 99.9%（1683 条） |
| ycggzy winning_amount | 0% | 30.0% |
| ycggzy deadline | 0% | 21.7% |
| ycggzy raw_json.content | 0% | 永久修复 |
| yancheng_gov purchaser | 96.8% | 98.3% |
| yancheng_gov budget（健康值）| 28.6% 含 80 条假数据 | 27.2% 全真 |
| yancheng_gov award winner | 99.1% | 99.3% |
| yancheng_gov open_date | 23.5% | 24.7% |

---

## 修复清单（v2.5 → v2.6，2026-06-26）

### 新增功能

| # | 内容 | 文件 |
|---|------|------|
| 106 | unified.db 新增 `other` 表（流标/终止/更正/合同，3031条），含 `notice_subtype` 细分 | `build_unified.py`、`crawlers/html_common.py` |
| 107 | `project_links` 关联表 + `project_chain` 视图（tender×award，68%覆盖，2652条）| `build_project_links.py`（新增）、`build_unified.py` |
| 108 | 流标/终止 5 维度报告（subtype/site/月趋势/行业/发包方），整体流标率 12.2% | `report_failed_bids.py`（新增）|
| 109 | 更正公告 open_date 联动（suffix 剥离 + jszbcg `【更正公告】` 前缀剥离）| `enrich_amendment_opendate.py`（新增）|
| 110 | 补全脚本统一入口（details/yancheng_gov/ocr/amendment 四步调度）| `reenrich.py`（新增）|
| 111 | yancheng_gov 批次意向公告展开（540条，59批次多项，表格→expected_list JSON）| `expand_intention.py`（新增）|

### 重构

| # | 内容 | 效果 |
|---|------|------|
| 112 | `enrich_details.py` 解耦：per-site 解析器迁入 `crawlers/`，日期工具提升到 `html_common.py`，测试迁到 `tests/` | 1082行→829行，新站点解析器无需修改主文件 |

### project_chain 视图关键指标（v2.6）

| 指标 | 数值 |
|------|------|
| tender×award 关联率 | 67%（2723/4035） |
| 平均招采周期 | 20 天 |
| 平均中标折扣率 | 83.7%（预算>1万，ratio 0.3~1.5 样本） |
| 含更正公告的链路 | 22%（598条，平均1.8次更正）|

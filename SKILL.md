---
name: yancheng-bidding-pro
description: 全域盐城招标数据采集（12站/12739条原始→unified.db）；触发词：全域招标 / 盐城招标 / 招标采集Pro；输出 unified.db + PDF月报 + PDF倒计时报告 + 运营商综合月报 + PDF采购意向报告（不导出Excel）
outputs:
  - sqlite  # data/unified.db（四张表：tender/award/intention/other + project_links + project_chain视图）
  - sqlite  # data/*.db（12个站点独立数据库）
  - sqlite  # data/tyc.db（天眼查运营商中标数据）
  - pdf     # output/盐开招标公告_YYYYMM.pdf（盐南+经开未分类招标公告月报）
  - pdf     # output/盐开开标倒计时报告_YYYYMMDD.pdf（盐南+经开未分类开标倒计时）
  - pdf     # output/盐城通信运营商中标报告_YYYY-MM.pdf（三源合并：ybp+tyc+obm）
  - pdf     # output/盐开采购意向报告_YYYYMM.pdf（盐南+经开采购意向月报）
version: v2.6
status: 生产可用
last_run: 2026-06-30
records: 12739条原始（12站）→ unified.db tender:3802/award:4035/intention:1143/other:3149；project_links:2723条(67%覆盖)

> **v2.6 变更（2026-06-26）**：① unified.db 新增 `other` 表（3031条，含 notice_subtype 细分）及 `project_links`/`project_chain`（tender×award 68%覆盖，均值20天周期/83.7%折扣率） ② `enrich_details.py` 解耦（1082→829行） ③ 新增 `reenrich.py`/`report_failed_bids.py`/`expand_intention.py`/`enrich_amendment_opendate.py`/`build_project_links.py`。
---

# 全域招标信息采集 Pro

## 概述

采集盐城市 12 个站点的招标/中标/采购意向公告，富化详情页字段，输出 unified.db 四张归一化表 + 四份 PDF 报告（不导出 Excel）。

**覆盖站点**：jszbcg（江苏招标采购服务平台）、yancheng_gov（盐城市政府采购网）、ycggzy（盐城市公共资源交易平台）、sufu（苏服务）、yueda（悦达集团阳光采购平台）、dushi（盐城市都市建设投资集团有限公司）、jscn（江苏世纪新城投资控股集团有限公司）、chennan（江苏省盐南高新区公共资源交易电子化服务平台）、dongfang（盐东方产业投资集团有限公司）、bigdata（盐城市大数据集团）、jingkai（盐城经开城市发展投资集团有限公司）、kaifaqu（盐城经济技术开发区行政审批局公共资源交易服务平台）

## 本地缓存架构（v1.4+）

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

# 第五步：生成 unified.db（四张表 + project_links + project_chain 视图）
python3 build_unified.py

# 第六步：数据质量验证
python3 verify_quality.py

# 可选：生成盐开月报 PDF
python3 generate_tender_report.py

# 可选：生成盐开开标倒计时报告 PDF
python3 generate_countdown_report_pdf.py

# 可选：生成运营商综合月报（三源合并）
python3 generate_operator_combined_report.py --month YYYY-MM

# 可选：生成盐开采购意向报告 PDF
python3 generate_intention_report.py YYYY-MM
```

> ⚠️ **不导出 Excel**：本 skill 输出四份 PDF 即可，Excel 不推送（避免群内刷屏）。`export_excel.py` 仅本地按需手动运行，不进 cron。

## 天眼查采集工作流（**每日自动** + Cookie 失效时手动）

```bash
cd ~/.openclaw/workspace/yancheng-bidding-pro

# 1. Cookie 过期时重新登录（手动）
python3 crawlers/tyc_login.py

# 2. 采集运营商中标数据（写入 data/tyc.db）— 每天 05:00 cron 自动跑
python3 crawlers/tyc_crawler.py

# 3. 生成运营商综合月报
python3 generate_operator_combined_report.py --month YYYY-MM
```

> 天眼查招投标权限基于会员（有效期 2028 年），但 Cookie 服务端失效无法从时间戳判断，建议每月手动登录一次。**每天自动采集 13 家运营商（约 25-30 分钟），Cookie 失效时会报错但不影响其他步骤继续。**

## 报告脚本

### 盐开招标公告月报（PDF）
```bash
python3 generate_tender_report.py [YYYY-MM]   # 默认当月
```
- 数据源：unified.db tender 表，std_district IN ('盐南','经开')
- 第1页：12站汇总表（今日/前日发布数、当月重点招标数、当月非相关招标数）
- 第2页起：各站未分类项目明细（潜在商机）
- 大站（≥8条）单独一页，0条站合并最后一页

### 盐开开标倒计时报告（PDF）
```bash
python3 generate_countdown_report_pdf.py [YYYY-MM-DD]   # 默认今日
```
- 数据源：unified.db tender 表，std_district IN ('盐南','经开') + proj_major_cat IS NULL + open_date >= 当月
- 清单一：未来开标（当日及以后，按开标时间升序）
- 清单二：本月已开标（昨日及以前，按开标时间倒序）
- 今日开标橙色高亮，3天内开标橙字标注

## 补充工具脚本

```bash
# 批量下载所有站点 HTML 详情页（首次初始化用，断点续传）
python3 download_site_pages.py [--site jscn dongfang ...]

# 批量下载 jszbcg 所有 PDF（首次初始化用，断点续传）
python3 download_jszbcg_pdfs.py

# 按项目名重命名已有 MD 文件
python3 rename_pages.py

# 清理 yancheng_gov art_20171 脏数据（默认dry-run，--confirm真删）
python3 cleanup_art_20171_dupes.py [--confirm]
```

## ycggzy 专用补采（发包单位 API 补全）

```bash
# ycggzy 是 SPA，purchaser 来自列表 API，不走 enrich_details
python3 reenrich_ycggzy.py --start 2026-05-01 --end 2026-06-22
```

## yancheng_gov Playwright 补全（按需）

yancheng_gov 部分记录因 WAF 返回 403，requests 抓不到，需 Playwright：

```bash
# 轻量版：只处理 detail_fetched=2 的失败记录
python3 enrich_yancheng_gov_playwright.py

# 完整版：Playwright + 表格专项解析，补全率更高
python3 enrich_yancheng_gov.py
```

## 调试 / 历史工具（非生产流程）

| 脚本 | 说明 | 状态 |
|------|------|------|
| `dry_run_v2.py` | 分类规则只读调试，验证 RULES 命中情况 | 按需 |
| `fix_titles.py` | 修复 yancheng_gov 141条乱码标题 | 已用完 |
| `migrate_from_old.py` | 从旧 history.db 迁移到 Pro DB | 已用完 |

## 数据质量现状（2026-06-26 v2.6）

### unified.db 四表

| 表 | 总条数 | 发包方 | 金额字段 | 开标时间 |
|----|------|--------|--------|--------|
| tender | 3802 | 90% | budget 81% | 90% |
| award | 4035 | 92% | winning_amount 75% / winner 87% | — |
| intention | 1143 | 98% | budget 99% | — |
| other | 3149 | — | — | — |

**project_links/project_chain（v2.6 新增）**
- tender×award 关联率：67%（2723/4035）
- 平均招采周期：20天；中标折扣率均值：83.7%
- 含更正公告链路：22%（598条）

> jszbcg 已覆盖 2026-01-04 至今全年历史

### 本地缓存覆盖

| 类型 | 数量 | 路径 |
|-----|------|------|
| HTML/ycggzy 详情页 MD | ~2900 个 | `data/pages/{site}/` |
| jszbcg PDF | ~1800 个 | `data/pdfs/jszbcg/` |

## 系统不变量（verify_quality.py 自动校验）

| 不变量 | 当前值 | 说明 |
|--------|-------|------|
| jszbcg 记录数 ≥ 3500 | 3549 | 历史补采后覆盖全年 |
| yancheng_gov 记录数 ≥ 1600 | 1665 | — |
| ycggzy 记录数 ≥ 1900 | 2012 | — |
| sufu purchaser 填充率 ≥ 99% | 100% | 纯 API |
| unified tender ≥ 3500 | 3714 | — |
| unified award ≥ 3500 | 3634 | — |

## 已知结构性限制

- **sufu 中标人 0%**：award 详情页为 JS SPA（js.fwgov.cn），静态抓取只返回空壳
- **yueda 预算 4%**：网站公告页本身不披露预算金额
- **yancheng_gov award winning_amount 44%**：框架协议类使用"优惠率"而非固定金额，无从提取
- **ycggzy 合同类记录无 page（2196条）**：raw_json.content 为空，ycggzy API 对合同履行类不返回 HTML

## 已知遗留问题

- **采购意向 expected_list（预计挂网时间）100% 空**：字段存在但未解析
- **std_category 覆盖率 ~42%**：规则持续扩充中
- **ycggzy purchaser 结构性缺口 ~300条**：SPA API，部分记录无法回填
- **yueda winner "项目名:公司名"格式**：部分候选人公示 winner 字段含项目名前缀，可后处理但优先级低

---

## 本轮修复清单（v2.5 → v2.6，2026-07-06）

### P0 重复入库修复（tyc + yancheng_gov + unified）

| # | 站点/文件 | 问题 | 根因 | 修复 | 效果 |
|---|----------|------|------|------|------|
| 98 | `crawlers/base.py` make_id | 同项目多包公告被分 2-N 条入库 | `project_name` 未去 "采购包N" 后缀 | `re.sub(r'(采购包\s*\d+\s*)$', '', project_name)` 再哈希 | 跨站去重 |
| 99 | `crawlers/tyc_crawler.py` make_id | tyc 同项目多包入库 | 同上 | 同上修复 | tyc 重复入库阻断 |
| 100 | `data/tyc.db` | 同 `detail_url` 重复入库 | 缺兜底 | `CREATE UNIQUE INDEX idx_tyc_detail_url ON tyc_awards(detail_url)` | 重复 INSERT 拒入 |
| 101 | `data/yancheng_gov.db` | 同上 | 同上 | `CREATE UNIQUE INDEX idx_notices_detail_url ON notices(detail_url)` | 重复 INSERT 拒入 |
| 102 | `data/unified.db` | 跨站 award 重复 | dedup_awards 漏跨日 | 新增 `_dedup_tenders` 按 (detail_url, publish_date) | rebuild 后 0 重复 |

**双保险机制**：make_id 防止（去后缀）+ DB UNIQUE INDEX 兜底（按 detail_url）。跨日期合法业务（ycggzy/dushi/chennan.notices 跨日变更、`unified.intention` 汇总页）不加 UNIQUE INDEX。

### P0 运营商报告金额单位修复（防"X万显示成X元"）

| # | 位置 | 问题 | 根因 | 修复 | 验证 |
|---|------|------|------|------|------|
| 103 | `generate_operator_combined_report.py` `load_tyc` | fire 项目 41.5万 被显示成 41元 | 注释写"万→元"但代码漏了 `* 10000` | 加回 `amount * 10000 if amount else None` | PDF PyPDF2 提取：41.5万 ✓ |
| 104 | 影响范围 | 50 条盐城 tyc 历史数据 < 1000 万 | 同一 bug | 改 1 行全部修复 | 7 月报告 4 条运营商记录全对 |

### 飞书推送 cron 升级 v2.4 → v2.6

| # | 变更 | 原因 | 验证 |
|---|------|------|------|
| 105 | cron 名称 `(v2.4)` → `(v2.6)` | 与 message 实际版本一致 | cron run 后 summary 4/4 一次通过 |
| 106 | grep `om_x[0-9a-f]+` → `om_[0-9a-f]+` | 实际 messageId 以 `om_` 开头，旧模式漏匹配导致 cron 报告一直显示"首次失败"假警报 | v2.6 跑后 4/4 全显示"首次成功" |
| 107 | `sleep 30s` → `sleep 5s` 重试间隔 | 飞书 API 瞬时失败多在 1-2s 恢复 | cron run 55.5s 完成（原本 90s+） |

**实锤证据**：v2.6 cron run（2026-07-06 16:19）4 份 PDF 全部一次推送成功，messageId `om_x100b6b821e70a4a0b1dae01db6d9f4f` 等 4 条 `openclaw message read --message-id` 全部 `ok: true`。

---

## 本轮修复清单（v2.3 → v2.4，2026-06-25）

### P0 数据误提取清除

| # | 站点 | 字段 | 问题 | 修复 | 数量 |
|---|------|------|------|------|------|
| 92 | jszbcg | budget | 文件工本费/单价（"/吨"/"/套"/"售后不退"）误作项目预算 | chunk 含上述词则 skip | 14条 |
| 93 | jszbcg | winner | "详见公告内容其他类型投标报价：..." 伪中标人 | 提取前检查 + SQL 清除 | 19条 |
| 94 | ycggzy | purchaser | `&nbsp;` HTML 实体残留 | `_clean_purchaser_val` 加 `html.unescape` | 9条 |

### P1 覆盖率提升

| # | 站点 | 字段 | 根因 | 修复 | 效果 |
|---|------|------|------|------|------|
| 95 | jszbcg | budget(tender) | jszbcg 固定格式"自筹资金/财政资金：XX万元"不在 BUDGET_KEYWORDS | 加入"自筹资金""财政资金""财政性资金" | 78%→**85%** |
| 96 | ycggzy | page_path(award/tender/other) | raw_json.content 被 `<![CDATA[...]]>` 包装，html2text 解析返回空 | `download_ycggzy` 剥除 CDATA 包装；设置后同步 `detail_fetched=0` | 新增**1390条** MD |
| 97 | yueda | winner(award) | "中标候选人名单 第一名：XXX"格式因"名单 第1名"超 5 字 colon 窗口而失配 | 独立 `m_cand` 正则 | 46%→**94%** |

---

## 本轮修复清单（v2.1 → v2.2，2026-06-25）

| # | 变更 | 说明 |
|---|------|------|
| 85 | 天眼查采集器 | 新增 `crawlers/tyc_crawler.py`（Playwright，采集13家运营商中标数据→tyc.db）；修复"中标方"检测逻辑（`inner_text()` 替代 `:text-is()`）|
| 86 | 天眼查登录工具 | 新增 `crawlers/tyc_login.py`（Playwright 登录/刷新 Cookie） |
| 87 | 运营商综合月报 | 新增 `generate_operator_combined_report.py`（三源合并：ybp+tyc+obm）；首页增加天眼查13家监控企业列表 |
| 88 | 运营商月报 | 新增 `generate_operator_award_report.py`（单站点运营商中标月报） |
| 89 | 区县打标 | `add_std_district.py` COMPANY_MAP 新增3所学校→盐南：盐城市第一中学、盐城市经贸高级职业学校、盐城市伍佑中学 |
| 90 | 数据质量基线 | `verify_quality.py` jszbcg purchaser 0.95→0.88（历史补录数据），unified coverage 95%→90%（跨站去重 ~8%） |
| 91 | 安全 | `.gitignore` 新增 `data/cookies.json`（天眼查敏感 Cookie） |

---

## 本轮修复清单（v2.0 → v2.1，2026-06-24）

### notice_type 误分类修正（51条）

| # | 问题 | 站点 | 数量 | 修复 |
|---|------|------|-----|------|
| 81 | "评审结果公示"/"询价结果公示" 被 `infer_notice_type` 默认归 tender | yueda（pfwgg/phwgg/pgcgg 路径）| 33 | `html_common.py` 加"结果公示"/"评审结果"关键词 → award |
| 82 | 同上 | dushi | 18 | 批量 UPDATE notice_type='award' |

unified.db：tender 3714→3674（-40）/ award 3634→3694（+60，含跨站去重变动）

### purchaser 提取修正（dushi 2441号）

| # | 问题 | 修复 |
|---|------|------|
| 83 | `格式8（因COMPANY经营需要）` 置于格式3之后，格式3从标题行抢先匹配"关于都市服务子公司" | 格式8移至兜底链最前 |
| 84 | `_parse_amount` 被"单价65元/月/台"抢先，总计32760未采集 | 开头加"总计XXX元"优先匹配 |

---

## 本轮修复清单（v1.9 → v2.0，2026-06-23）

### purchaser 全面清洗（155条）

| # | 问题类型 | 数量 | 修复方式 |
|---|---------|-----|--------|
| 72 | jszbcg award `中标候选人（XXX）` 误入 purchaser（winner 段落被抓为发包方） | 79 | NULL + 修复根因 |
| 73 | jszbcg `【招标公告/中标结果/暂停/流标公告】XXX` 标题前缀残留 | 16 | 剥前缀 |
| 74 | jszbcg/yancheng_gov `单位名称：/招标人：/采购人：` 冗余前缀 | 21 | 剥前缀 |
| 75 | jszbcg/yancheng_gov `XXX地址：.../联系人：...` 后缀描述混入 | 14 | 截断地址后缀 |
| 76 | jscn `[上一篇]()[XXX]` 导航残留 | 4 | 剥前缀 |
| 77 | dushi/yancheng_gov/ycggzy 纯描述段落/垃圾文本 | 21 | NULL |

**新增函数**：`_clean_purchaser_val(val)` — 统一剥除 `【xxx】`、`招标人：`、`地址：...`、`联系人：...` 等前后缀噪声，在 `_is_valid_purchaser` 校验前调用。

**新增拒绝规则**：`_is_valid_purchaser` 增加 `^中标(?:候选人|结果|公示|公告)` 前缀拒绝，防止 winner 段落误入 purchaser。

### jszbcg OCR singleton 优化

| # | 问题 | 修复 |
|---|------|------|
| 78 | `_pdf_to_md` 每次调用新建 `PaddleOCR()` 实例，加载5个 PaddleX 模型（~10-20s/次），批量处理1000+条时耗时数小时 | `crawlers/jszbcg.py` 新增模块级 `_OCR_INSTANCE` + `_get_ocr()` singleton 函数，全批次只初始化一次 |

### 历史数据回填

| # | 站点 | 操作 | 新增记录 |
|---|------|------|--------|
| 79 | jszbcg tender | 补采 2026-01-04~04-19（原始 tender 仅从 04-20 开始） | +1065条，现覆盖 2026-01-04 至今 |
| 80 | chennan/kaifaqu/jscn/dongfang | 翻页 bug 修复后历史重采（2026-01-04~06-19） | ~42条 |

---

## 本轮修复清单（v1.7 → v1.8，2026-06-22）

### crawlers/base.py — binding 16/20 错误根治（1项）

| # | 问题 | 修复 |
|---|------|------|
| 59 | `SiteDB.insert()` 的 UPDATE 两条路径直接将 record dict 传参，当 record 缺少 `page_path`/`pdf_path` 等字段时抛 `sqlite3.ProgrammingError: binding 16`，导致 ycggzy/yancheng_gov/jszbcg 等站回填历史数据时中断 | 新增 `_build_params(record, cols)` helper：从 record 按 cols 列表取值，缺 key 补 None；INSERT + UPDATE 三条路径全部走 helper |

影响站点：ycggzy（政府采购等后段分类）、yancheng_gov（四种 notice_type 全报）、jszbcg（bulletinType 4/6 终止/不招标公示）

### crawlers 翻页 break 逻辑 bug（4站）

| # | 问题 | 修复 |
|---|------|------|
| 60 | chennan/kaifaqu/jscn/dongfang 四站：翻页时 page 1 数据全 > end_date 被过滤后 items=[]，触发 `if not items: break` 立即退出，导致回填 1-4 月时 0 条（深页数据完全丢失） | 删除 `if not items: break`，只保留 `if not items and page_exhausted: break`（翻过 start_date 才终止）；外层 `for page in range(1, N)` 限制最大页数防死循环 |

验证（修复前 0 条 → 修复后）：chennan 3-4月 19条、kaifaqu 21条、jscn 13条、dongfang 30条

> ⚠️ 注意：上述两个修复已提交但**历史数据（1-4月）尚未回填**，等待拍板后执行 `run_collection.py --days 120` 补跑。

---

## 本轮修复清单（v1.8.1 → v1.9，2026-06-23）

### enrich_details.py 全局字段补全（9项）

| # | 问题 | 修复 |
|---|------|------|
| 63 | yancheng_gov "采购人员名单：专家名" 被"采购人"关键词误匹配，返回专家名 | `PURCHASER_KEYWORDS` 首位插入"采购人信息"，先匹配"采购人信息单位名称：XXX" |
| 64 | `_ORG_SUFFIX` 单字"场""校""部"过泛，误匹配"小剧场""隔油池部" | 移除"场""部""校"，保留"馆"（博物馆/美术馆） |
| 65 | purchaser/winner 内层关键字跳转在句中出现时触发（"（即采购人）"型），导致跳到无效位置 | 内层跳转改为"关键字后紧跟冒号才跳"（`next[0] in '：:'`），原位置阈值改为语义条件 |
| 66 | yueda 格式"悦达融资租赁有限公司关于批量案件的公告"无标准关键词 | 格式6：`org_name + 关于 + … + 公告/招标/询价` 主语捕获 |
| 67 | dongfang/dushi/jscn 无标准采购人标签，网页底部版权行含公司名 | 格式7：`Copyright…公司名` 或 `版权所有：公司名` 兜底 |
| 68 | jszbcg PDF "投标报价金额：8.54万元" 未被采集 | `WIN_AMOUNT_KEYWORDS` 加"投标报价金额/中标报价金额/成交报价金额/报价金额" |
| 69 | jszbcg award "中标人信息：项目名：中标人：公司"格式，中标人信息：先匹配 | winner 提取加内层跳转，跳到真正"中标人：公司" |
| 70 | jszbcg award PDF→MD fallback 只补 purchaser，winner/winning_amount/budget 仍空 | 扩展 fallback 循环：`("purchaser","winner","winning_amount","budget","budget_unit","budget_text")` |
| 71 | "沪苏、三龙污水厂"型地名枚举被误识别为发包人 | `_is_valid_purchaser` 新增：含"X、Y"汉字枚举模式（`[一-鿿]{2,}、[一-鿿]{2,}`）拒绝 |

改善效果（与本次审计前对比）：

| 表 | 字段 | 修复前缺失 | 修复后缺失 | 新增填充 |
|----|------|----------|----------|---------|
| tender | 发包方 | 515 (20%) | 257 (10%) | +258 |
| tender | 预算金额 | 723 (28%) | 529 (20%) | +194 |
| award | 发包方 | 1429 (40%) | 195 (6%) | +1234 |
| award | 中标金额 | 2009 (57%) | 913 (26%) | +1096 |
| intention | 发包方 | 18 (2%) | 18 (2%) | — |
| intention | 预算金额 | 443 (46%) | 443 (46%) | — (结构性) |

### 剩余结构性缺口（无法通过MD补全）

| 站点/场景 | 字段 | 缺口数 | 原因 |
|---------|------|--------|------|
| ycggzy | 发包方 | ~189 | SPA API，reenrich_ycggzy.py 698条未匹配 |
| yancheng_gov | 中标金额 | ~294 | 部分中标公告网页结构无金额字段 |
| jszbcg award | 中标金额 | ~308 | 候选人公示类PDF无最终成交金额 |
| yancheng_gov intention | 预算 | 437 | 采购意向公告本身不披露预算 |
| yueda全站 | 预算/中标金额 | 全空 | 平台公告页本身不披露金额 |

---

## 本轮修复清单（v1.8 → v1.8.1，2026-06-22）

### enrich_details.py purchaser 鲁棒性修复（4项）

| # | 问题 | 修复 |
|---|------|------|
| 59 | `_is_valid_purchaser` 不拦截圈号①②③...（Unicode No 类，不被 `\d` 匹配），导致"③供应商在参加政府..."被误入库 | 新增 `_CIRCLE_NUM_RE`，在 start-char 检查后独立过滤 |
| 60 | `_BAD_PURCHASER_RE` 漏网：参与/属于/适用政府采购、失信被执行人名单、报名地点/领取地点 | 扩充正则，覆盖更多资格要求片段 |
| 61 | jszbcg PDF 中"招标人为XXX"无冒号格式，`_extract_after_keyword` 无法匹配；以及格式2/格式5匹配到"一、XXX公司"后含序号前缀被 `_is_valid_purchaser` 拦截 | 新增格式5 fallback（`re.sub(r'\s+', ' ', text)` 跨行合并后匹配"招标人为XXX"）；所有 fallback 匹配结果统一剥除序号前缀 `re.sub(r'^[一二三四五六七八九十①-⑩][、.．]\s*', '', val)` |
| 62 | jszbcg `enrich_from_raw_json_jszbcg` 仅从 `projectCompany` 取 purchaser，当 API 字段为空且本地 PDF→MD 缓存存在时，无法补全 | `enrich_site('jszbcg')` 中：`projectCompany` 为空时降级读 `page_path` 本地 MD，走 `parse_html_detail` 补全 |

修复后：jszbcg 7条"一、XXX"前缀历史记录全部重新提取，其中6条自动正确，1条（无 page_path）手动写入。

---

## 本轮修复清单（v1.6.1 → v1.7，2026-06-22）

### enrich_details.py 富化修复（6项）

| # | 问题 | 修复 |
|---|------|------|
| 39 | `_extract_after_keyword` 不剥 Markdown `**` 符号，导致 `**五、开启**↵时间：` 合并后变 `开启**时间：`，关键词匹配断裂（yancheng_gov 25条无 open_date） | `_extract_after_keyword` 加一行：`re.sub(r'[*_~\`]', '', ...)` 剥 MD 符号，**影响所有站点所有关键词** |
| 40 | `_parse_datetime` 不识别全角冒号"："（chennan "15：00时" 无法解析） | `_parse_datetime` 加 `raw.replace('：', ':')` |
| 41 | `_parse_datetime` 不识别"点"分隔符（kaifaqu "15点00分" 无法解析） | `[时:]` → `[时:点]` |
| 42 | chennan "递交截止时间（开标时间）**_YYYY年…**前" 无冒号，`_extract_after_keyword` 失败 | 新增 fallback regex：剥 MD 后匹配"递交截止时间[…]{0,25}YYYY年…" |
| 43 | `OPEN_DATE_KEYWORDS` 缺"开启时间"（kaifaqu/yancheng_gov "五、开启 时间：" 格式） | 加入"开启时间" |
| 44 | `DEADLINE_KEYWORDS` 缺"截止时间"（kaifaqu "截止时间：YYYY-MM-DD" 格式） | 加入"截止时间" |

### add_std_category.py 分类规则（10项）

| # | 新增规则 | 触发词样例 |
|---|---------|---------|
| 45 | 垃圾与环卫 must_any + | 化粪池、管网疏通、管道疏通、下水道疏通 |
| 46 | 房屋招租 must_not 去掉"数字化"；must_any + | 招租公告（防"数字化交易云平台"误杀） |
| 47 | 电梯服务 must_any + | 电梯检验、电梯年检、电梯年度检验、电梯维护 |
| 48 | 机电设备维修安装 must_any +；must_not 精确化 | 机电安装、设备安装工程、压力容器安装（防"汽车平台"误杀） |
| 49 | 高标准农田建设 must_any + | 永久基本农田、农田布局、耕地保护、农田优化 |
| 50 | 工程保险 must_any + | 三责险、三者责任险、非机动车保险、车辆保险、险种采购 |
| 51 | 房屋维修 must_any + | 楼顶改造、储物空间、增加储物 |
| 52 | 物业管理 must_any + | 应急物资保养、仓库保养、应急物资维护 |
| 53 | 房建工程 must_any + | 提升改造、阳台改造 |
| 54 | 环保检测评估 must_any + | 安全鉴定、建筑安全鉴定、房屋安全鉴定、地块安全鉴定 |

### add_std_district.py 区县打标（1项）

| # | 问题 | 修复 |
|---|------|------|
| 55 | jszbcg 盐南/经开记录被 region 字段误标为亭湖/盐都（发包方实为盐南/经开单位） | 新增 step 2c：jszbcg 专项，purchaser 含盐南/经开关键词时覆盖 region 派生值 |

### build_unified.py + 爬虫修复（3项）

| # | 问题 | 修复 |
|---|------|------|
| 56 | yancheng_gov COLUMNS[20171] 实为公开招标跳转页，与 20174/… 重复入库 66 条，open_date 全空 | `crawlers/yancheng_gov.py` 注释删除 COLUMNS[20171] |
| 57 | unified.db 遗留 66 条 art_20171 脏数据 | `cleanup_art_20171_dupes.py` --confirm 真删，自动备份 |
| 58 | build_unified.py 未过滤 art_20171 URL（防未来残留） | 加 `_BAD_URL_PAT = re.compile(r'art_20171_')` 过滤 |

### 新增脚本（2个）

| 脚本 | 说明 |
|------|------|
| `generate_countdown_report_pdf.py` | 盐开开标倒计时报告（PDF/A4横向），清单一：未来开标，清单二：本月已开标，今日橙色高亮 |
| `generate_countdown_report.py` | 同上 Excel 版（兼容备用） |

---

## 本轮修复清单（v1.5 → v1.6，2026-06-22）

| # | 问题 | 修复位置 |
|---|------|---------|
| 32 | 化粪池清运/管网疏通未归类 | `add_std_category.py` 垃圾与环卫 |
| 33 | 房屋招租被"数字化交易云平台"误杀 | `add_std_category.py` |
| 34 | 电梯年度检验/维护未归类 | `add_std_category.py` 电梯服务 |
| 35 | std_category 覆盖率 45%→47% | 1844/3920 |
| 36 | 月报格式重构 | `generate_tender_report.py`：汇总表列名/明细页逻辑/未分类展示 |

## 本轮修复清单（v1.6 → v1.6.1，2026-06-22）

| # | 问题 | 修复位置 |
|---|------|---------|
| 37 | yancheng_gov columnid=20171 脏数据源 | `crawlers/yancheng_gov.py` 删除 COLUMNS[20171] |
| 38 | unified.db 残留 66 条历史脏数据 | `cleanup_art_20171_dupes.py` |

## 本轮修复清单（v1.4 → v1.5，2026-06-21）

| # | 问题 | 修复位置 |
|---|------|---------|
| 28 | tender 表混入最高限价公示 | `build_unified.py` |
| 29 | std_category 覆盖率 43%→45% | `add_std_category.py` 新增30+关键词 |
| 30 | 资产处置类规则 must_not 不全 | `add_std_category.py` |
| 31 | 新增盐开招标公告月报 | `generate_tender_report.py` |

## 本轮修复清单（v1.3 → v1.4，2026-06-21）

| # | 问题 | 修复位置 |
|---|------|---------|
| 26 | jszbcg 富化依赖单独 OCR 步骤 | `crawlers/jszbcg.py` PDF→MD pipeline 内置化 |
| 27 | run_daily.sh 7步改6步 | `run_daily.sh` |

## 注意事项

- jszbcg OCR：图片型 PDF ~40s/条；增量运行只处理新增记录
- 本地缓存后，`enrich_details.py` 重跑不联网
- `build_unified.py` 会覆写 `data/unified.db`；各站 *.db 保留原始数据
- `data/` 目录（含 DB、PDF、MD 文件）已加入 `.gitignore`，不随代码提交

---

## 本轮修复清单（v2.2 → v2.3，2026-06-25）

### cron stall timeout 修复（修复 #92）

| # | 问题 | 修复 |
|---|------|------|
| 92 | 05:00 cron 用 `agentTurn` 模式调度 9 步 Python 脚本，agent exec 后长时间无新 model call → 系统判定 stall → 10 分钟后超时 | 新增 `run-full-pipeline.sh` bash 脚本（10 步独立脚本）；cron payload 改为调一行 `bash run-full-pipeline.sh`；timeout 1800s → 3600s |

**验证**：手动跑 4 分钟完成全流程（含天眼查 + 12站 + 4 份 PDF）。原 6/24 05:00 cron 10 分钟超时问题根治。

### tyc_crawler 提速 10 倍（修复 #93）

| # | 问题 | 修复 |
|---|------|------|
| 93 | `crawlers/tyc_crawler.py` 默认不传 `--days`，13 家运营商每家翻满 20 页（`MAX_PAGES=20`），全量采集约 45 分钟 | `run-full-pipeline.sh` 调用时传 `--days 1`，采集器第 1 页检测到超出窗口立即停止翻页；13 家合计 4 分钟 |

**原理**：cron 每天跑，DB 里已有数据。`--days 1` 仅取近 1 天，去重后新增基本为 0，但提前停止翻页效率提升 10 倍。

### 取消 Excel 推送（修复 #94，三处同步）

| # | 位置 | 改动 |
|---|------|------|
| 94a | `SKILL.md` | outputs 移除 excel；流程示例删除 `export_excel.py` 步骤；加⚠️ 说明「不导出 Excel」 |
| 94b | `run-full-pipeline.sh` | 移除 `[Extra] export_excel.py` 步骤 |
| 94c | cron job `f605317e-...` | 08:30 推送移除 Excel，只推 3 份 PDF（后续升级为 4 份） |

**说明**：`export_excel.py` 脚本保留，需要时手动运行即可，不进生产流程。

### 修复后 cron 任务清单（当前状态）

| cron 时间 | 任务 | 调用的脚本 | 超时 |
|---------|------|-----------|------|
| 05:00 全流程 | `yancheng-bidding-pro daily 5:00 full pipeline` | `bash run-full-pipeline.sh` | 3600s |
| 08:35 推送 | `yancheng-bidding-pro push 4 PDFs to feishu group 8:30 (v2.6)` | openclaw message send ×4（含预检探测 + 失败重试） | 1800s |

**预期耗时**：05:00 cron 完整跑 ≈ 8-10 分钟（天眼查 4min + 12站采集 4min + 4份报告生成 <1min）。08:35 推送 ≈ 1-2 分钟（channel-info 预检 + 4次 send，失败 sleep 5s 重试 1 次，v2.6 修复后几乎不需重试）。

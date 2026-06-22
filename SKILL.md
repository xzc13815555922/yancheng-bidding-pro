---
name: yancheng-bidding-pro
description: 全域盐城招标数据采集（12站/3860条原始→unified.db）；触发词：全域招标 / 盐城招标 / 招标采集Pro；输出 unified.db + Excel + PDF月报 + PDF倒计时报告
outputs:
  - sqlite  # data/unified.db（三张表：tender/award/intention）
  - sqlite  # data/*.db（12个站点独立数据库）
  - excel   # output/盐城市全域招标信息_vN_YYYYMMDD_HHMM.xlsx
  - pdf     # output/盐开招标公告_YYYYMM.pdf（盐南+经开未分类招标公告月报）
  - pdf     # output/盐开开标倒计时报告_YYYYMMDD.pdf（盐南+经开未分类开标倒计时）
version: v1.7
status: 生产可用
last_run: 2026-06-22
records: 3860条原始（12站）→ 发包单位=3715 / 预算=1601 / 开标时间=1327 / 中标单位=1269
---

# 全域招标信息采集 Pro

## 概述

采集盐城市 12 个站点的招标/中标/采购意向公告，富化详情页字段，输出 unified.db 三张归一化表 + Excel + PDF报告。

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

# 第五步：生成 unified.db（三张表）
python3 build_unified.py

# 第六步：数据质量验证
python3 verify_quality.py

# 可选：生成盐开月报 PDF
python3 generate_tender_report.py

# 可选：生成盐开开标倒计时报告 PDF
python3 generate_countdown_report_pdf.py

# 可选：导出 Excel
python3 export_excel.py
```

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

## 数据质量现状（2026-06-22）

### 全站汇总（3860条原始）

| 字段         | 填充数  | 填充率 |
|------------|--------|------|
| purchaser  | 3715   | 96%  |
| budget     | 1601   | 41%  |
| open_date  | 1327   | 34%  |
| winner     | 1269   | 33%  |
| std_district | ~98% | add_std_district.py |
| std_category | 48%  | 规则持续扩充 |

### 各站概况

| 站点           | 条数   | 发包单位 | 预算 | 开标时间 | 中标单位 |
|--------------|------|--------|-----|--------|--------|
| jszbcg       | 1308 | 1290   | 484 | 571    | 571    |
| yancheng_gov | 790  | 774    | 264 | 195    | 143    |
| ycggzy       | 1289 | 1207   | 567 | 344    | 484    |
| sufu         | 195  | 195    | 195 | 47     | 0      |
| yueda        | 84   | 77     | 3   | 51     | 23     |
| dongfang     | 44   | 36     | 19  | 24     | 11     |
| jscn         | 41   | 38     | 17  | 24     | 12     |
| dushi        | 35   | 27     | 17  | 31     | 10     |
| chennan      | 31   | 29     | 17  | 19     | 8      |
| kaifaqu      | 30   | 30     | 12  | 15     | 2      |
| bigdata      | 10   | 10     | 5   | 5      | 4      |
| jingkai      | 3    | 2      | 1   | 1      | 1      |

### 本地缓存覆盖

| 类型 | 数量 | 路径 |
|-----|------|------|
| HTML 详情页 MD | ~1130 个 | `data/pages/{site}/` |
| jszbcg PDF | ~1300 个（616MB） | `data/pdfs/jszbcg/` |

## 系统不变量（verify_quality.py 自动校验）

| 不变量 | 当前值 | 说明 |
|--------|-------|------|
| jszbcg 记录数 ≥ 1300 | 1308 | 采集范围退化则告警 |
| yancheng_gov 记录数 ≥ 850 | 790 | art_20171 清理后正常下降 |
| ycggzy 记录数 ≥ 1280 | 1289 | — |
| sufu purchaser 填充率 ≥ 99% | 100% | 纯 API，无理由低于此 |
| jszbcg purchaser 填充率 ≥ 95% | ~98.6% | tenderName API 回填 |
| unified tender/award 各 ≥ 1200 | 1226/1234 | — |

## 已知结构性限制

- **sufu 中标人 100% 空**：列表API不含，详情API需登录，无法修复
- **yueda 预算 97% 空**：网站公告页本身不披露预算金额
- **ycggzy purchaser** 来自列表API（`reenrich_ycggzy.py`），不走 `enrich_details.py`

## 已知遗留问题（待决策）

- **yancheng_gov 10组重复记录**：同名同日期不同 art_id，疑似多标包；is_duplicate 未标记
- **采购意向 expected_list（预计挂网时间）100% 空**：字段存在但未解析
- **std_category 覆盖率 48%**：规则持续扩充中
- **sufu binding 16 报错**：苏服务API参数偶发，不影响存量数据

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

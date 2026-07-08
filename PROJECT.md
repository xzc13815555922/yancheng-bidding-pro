# 盐城市全域招标信息采集系统 Pro

> 项目全景图 **v2.7** | 2026-07-07 | 同步至 README v2.7（2026-07-06）

盐城市 12 个招标网站的全域采集、富化、关联、报告生成系统。覆盖招标/中标/采购意向/流标 4 类公告，含 PDF 月报、运营商综合月报、中小微专题、飞书群每日推送。

---

## 一、项目定位

| 维度 | bidding-assistant（旧） | **Pro v2.7** |
|------|------------------------|--------------|
| 覆盖范围 | 盐南 + 经开 | 盐城市**全域 12 站** |
| 数据库 | 单一 history.db | 每站独立 DB + **unified.db 4 表** |
| 公告类型 | 仅招标 | **4 类全采**（tender/award/intention/other）|
| 详情页 | 部分 | 全量补全 + **本地 MD 缓存** |
| 实时推送 | 无 | **每日 5:00 cron + 飞书群推送** |
| 报告维度 | 仅月报 | **4 份 PDF**（招标/倒计时/意向/运营商综合）|
| 关联分析 | 无 | **project_links**（tender×award 65%）+ project_chain 视图 |
| 行业专题 | 无 | **中小微专题**（sme_target 三分类）|

> **v2.7 更新 (2026-07-06)**：从"采集+月报"升级为"采集+富化+关联+专题+多维 PDF"完整流水线；代码量 **14181 行 / 60 .py 文件**。

---

## 二、系统架构

```
┌──────────────────── 采集层 12 站 + 1 站天眼查 ────────────────────┐
│  API直连(sufu/jszbcg/ycggzy) │ HTML解析(9站) │ Playwright(tyc)  │
│            ↓ 详情页补全 + 本地 MD 缓存(data/pages/{site}/*.md)     │
└─────────────────────────────┬──────────────────────────────────────┘
                              ↓ 每站独立 .db（12 个）
┌───────────── 存储层 unified.db 4 表 + 关联 + 视图 ────────────────┐
│  tender 4010 / award 4361 / intention 1194 / other 3432            │
│  + project_links 2843（关联率 65.2%）+ project_chain VIEW         │
└─────────────────────────────┬──────────────────────────────────────┘
                              ↓ build_project_links.py
┌─────────────── 报告层 4 份 PDF + 1 份 Excel 备用 ─────────────────┐
│  招标公告月报 / 采购意向月报 / 开标倒计时日报 / 运营商综合月报     │
│  招标/意向 PDF 含 sme_target 中小微三色标记（v2.7）               │
└─────────────────────────────┬──────────────────────────────────────┘
                              ↓ run-full-pipeline.sh（10 步，55s）
┌─────────────────── 推送层 cron 5:00 飞书群 ──────────────────────┐
│  v2.6 实测 4/4 全绿（messageId om_x... 全部 ok:true）             │
└──────────────────────────────────────────────────────────────────┘
```

> **v2.7 更新 (2026-07-06)**：新增关联层（v2.6）+ 中小微专题（v2.7）+ 推送层实测稳定。

---

## 三、公告类型（4 类全采）

| notice_type | 中文 | unified 表 | 行数 | 关键覆盖 |
|-------------|------|-----------|------|---------|
| `tender` | 招标公告 | `tender` | 4010 | open_date 90% / budget 81% / std_district 98% |
| `intention` | 采购意向 | `intention` | 1194 | budget 99% / **真项目名 98.7%**（v2.7 修复后） |
| `award` | 成交/中标 | `award` | 4361 | winner 87%（sufu 0%）/ winning_amount 75% |
| `other` | 流标/终止/更正/合同 | `other` | 3432 | notice_subtype 细分，整体流标率 12.2% |

> **v2.7 更新 (2026-07-06)**：`other` 表 v2.6 新增；`project_links` 将 tender×award 关联（65% 覆盖），含 22% 链路带更正公告（平均 1.8 次）；平均招采周期 **20 天**，平均中标折扣率 **83.7%**。

---

## 四、12 个网站采集规划

| # | 简称 | 中文名 | 方式 | 当前类型 | 状态 |
|---|------|--------|------|---------|------|
| 1 | jszbcg | 江苏招标采购服务平台 | API+PDF→MD | 4 类 | ✅ v2.7 open_date 真值修复 1683 条 |
| 2 | yancheng_gov | 盐城市政府采购网 | columnid API | 4 类 | ✅ purchaser 98.3% / budget 27.2% |
| 3 | ycggzy | 盐城公共资源交易 | SPA API | 4 类 | ✅ content 永久保留，winning_amount 30% |
| 4 | sufu | 苏服采 | POST API | 4 类 | ⚠️ 中标 100% 空（详情 API 需登录） |
| 5 | yueda | 悦达集团 | HTML | tender/award | ⚠️ 预算 97% 空 |
| 6-10 | dongfang/jscn/dushi/chennan/kaifaqu | 5 家国企/区平台 | HTML | tender/award | ✅ |
| 11 | bigdata | 盐城市大数据集团 | HTML | tender/award | ⚠️ 仅展示最近 10 页 |
| 12 | jingkai | 经开城发集团 | HTML | tender/award | ✅ v2.6 新增 |
| 附 | tyc | 天眼查运营商中标 | Playwright | award（运营商） | ✅ cron 5:00，--days 1 提速 11x |

> **v2.7 更新 (2026-07-06)**：v2.6 新增 jingkai + bigdata 凑齐 12 站；`download_site_pages.py` 补 `import re` 隐藏 bug（#95），新数据 page_path 38.8%→77.0%。

---

## 五、数据库设计

### 5.1 每站独立 DB（v0.2 设计保留）

`data/{site}.db` 主表 `notices`：统一核心字段 + 全量 `raw_json` + `detail_fetched` 状态。**v2.7 新增**：tyc.db + yancheng_gov.db 加 `UNIQUE INDEX(detail_url)` 兜底去重。

### 5.2 unified.db schema（v2.7 实测）

```sql
-- 4 张业务表（精简列）
CREATE TABLE tender (id PK, site_name, std_district, proj_major_cat,
    proj_minor_cat, publish_date, project_name, purchaser, budget,
    open_date, deadline, detail_url);
-- award / intention / other 结构类似

-- 关联层（v2.6 新增）
CREATE TABLE project_links (
    award_id PK REFERENCES award(id),
    tender_id REFERENCES tender(id),
    canonical_name, match_type, amendment_count DEFAULT 0
);

-- 链路视图（v2.6 新增，17 字段）
CREATE VIEW project_chain AS
SELECT t.id AS tender_id, a.id AS award_id, a.winner, a.winning_amount,
       pl.match_type, pl.amendment_count,
       julianday(a.publish_date) - julianday(t.publish_date) AS cycle_days
FROM project_links pl JOIN tender t ON t.id=pl.tender_id
                      JOIN award  a ON a.id=pl.award_id;
```

> **v2.7 更新 (2026-07-06)**：unified.db 从"合并表"升级为"4 表 + 关联 + 视图"三层；`_dedup_tenders` 跨日去重（#117）；intention 真项目名 43.9%→98.7%（#128/#129）。

---

## 六、详情页补全策略

```
采集列表 → 入库(detail_fetched=0)
    └→ 拉 detail_url → 转 MD → 缓存 data/pages/{site}/{项目名}.md
           └→ 解析：发包单位 / 预算 / 开标时间 / 截止时间
                  └→ UPDATE ... detail_fetched=1
```

- **v1.4 起本地缓存**：重跑无需联网
- **v2.6 解耦**：per-site 解析器迁入 `crawlers/{jszbcg,sufu}_parser.py`，主文件 1082→829 行
- **反爬**：间隔 0.5-1.5s / 失败重试 3 次 / detail_fetched=2 跳过

> **v2.7 更新 (2026-07-06)**：`reenrich.py` 补全统一入口（4 步调度）；`scripts/legacy/reenrich_jszbcg_open_date.py` 真开标时间解析（1683 条，99.9% 合理性）。

---

## 七、开发阶段规划

| Phase | 时间 | 内容 | 状态 |
|-------|------|------|------|
| Phase 1 | 2026-06-17 | 采集框架 + API 站 | ✅ |
| Phase 2 | 2026-06-25 | HTML 站 + 富化层 | ✅ |
| Phase 2.5 | 2026-06-26 | unified.db 4 表 + project_links + view | ✅ |
| Phase 3 | 2026-07-06 | cron + 飞书群 + 中小微 + 4 份 PDF | ✅ |
| Phase 4 | 待排期 | Web 前端 + 跨站去重增强 | 🔵 |

> **v2.7 更新 (2026-07-06)**：Phase 2-3 全部从 v0.2 "待排期"超期完成；v2.7 累计修复 **#92-#131 共 40 项**（v0.2 时为 0）。

---

## 八、项目目录结构

```
yancheng-bidding-pro/
├── PROJECT.md / README.md / scripts/legacy/cleanup_orphan_dbs.py (P2-1 新增)
├── data/  12 站 .db + unified.db + pages/ + pdfs/ + backup/
├── crawlers/
│   ├── base.py / html_common.py
│   ├── jszbcg_parser.py / sufu_parser.py  ← v2.6 解耦新增
│   ├── {jszbcg,ycggzy,yancheng_gov,sufu}.py
│   ├── {yueda,dongfang,jscn,dushi,chennan_kaifaqu,bigdata,jingkai}.py
│   └── tyc_crawler.py / tyc_login.py
├── tests/test_enrich_details.py  ← v2.6 单测
├── enrich_details.py (829行, v2.6 解耦)
├── reenrich.py / enrich_amendment_opendate.py / scripts/utils/expand_intention.py
├── extract_sme_target.py  ← v2.7 中小微专题新增
├── build_unified.py / build_project_links.py
├── add_std_district.py / add_std_category.py
├── run_collection.py / export_excel.py (按需手动)
├── report_failed_bids.py
├── generate_{tender,intention,countdown_report,countdown_report_pdf,operator_award,operator_combined}_report.py
├── rules/category.yaml (48 条, v2.5)
├── scripts/legacy/   一次性 / 已用完脚本（v2.6-v2.7 沉淀）
│   ├── reenrich_*.py (4 个站点补采)
│   ├── fix_titles.py / fix_unique_index_scope.py
│   ├── cleanup_art_20171_dupes.py / cleanup_orphan_dbs.py
│   └── migrate_from_old.py
├── scripts/utils/    长期工具（产品级入口或可复用）
│   ├── expand_intention.py        批次意向展开
│   └── migrate_unified_schema.py  unified.db schema 迁移
└── logs/
```

> **v2.7 更新 (2026-07-06)**：v2.6-v2.7 共新增 6 个脚本（reenrich/extract_sme_target/build_project_links/report_failed_bids/expand_intention/enrich_amendment_opendate）+ tests/ 目录。

---

## 九、待确认项（v2.7 当前未决）

- [ ] Web 前端技术栈（v0.2 延续）
- [ ] 是否升级 PostgreSQL（当前 SQLite 够用）
- [ ] 5 分钟级增量推送必要性（每日推送已满足）
- [ ] 中小微专题深度（当前 13.8% tender 命中，是否做"中小微专属"PDF 子集？）
- [ ] tyc 招投标数据会员续费（当前有效期至 2028 年）
- [ ] 跨站 tender×award 复杂多包去重（v2.7 已用"采购包N"后缀剥离）

> **v2.7 更新 (2026-07-06)**：v0.2 待确认 6 项中 3 项已确认（苏服采 serviceType ✅ / ycggzy subcode ✅ / 飞书群推送 ✅），3 项仍待定 + 3 项 v2.7 新增未决。

---

*最后更新：2026-07-07 P3-2 v0.2 → v2.7 同步完成*
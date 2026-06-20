# 盐城市全域招标信息采集系统 Pro
> 项目全景图 v0.2 | 2026-06-17 | 需求收集中，持续更新

---

## 一、项目定位

| 维度 | 现有 bidding-assistant | Pro 版（本项目） |
|------|----------------------|----------------|
| 覆盖范围 | 盐南高新区 + 经开区 | **盐城市全域** |
| 数据库 | 单一合并 history.db | **每网站独立 .db** |
| 入库字段 | 裁剪后的 ~26 列 | **全列入库 + raw_json** |
| 公告类型 | 仅招标公告 | **4 类全采** |
| 详情页 | 部分补充 | **全量补全关键字段** |
| 实时推送 | 无 | **5 分钟级** |
| 报告维度 | 仅月报 PDF | **县区维度 + 实时 + 月报** |
| Web 前端 | 无 | **规划中** |

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                       【采集层】12 个网站                         │
│                                                                  │
│  API直连类                    HTML解析类           Playwright类  │
│  ┌──────────┐ ┌──────────┐   ┌────────┐ ...       ┌──────────┐ │
│  │ 苏服采   │ │江苏招标  │   │政府采购│           │盐城公共  │ │
│  │(4类)     │ │采购服务  │   │网(15栏)│           │资源交易网│ │
│  └────┬─────┘ └────┬─────┘   └───┬────┘           └────┬─────┘ │
│       │             │              │                    │        │
│  ┌────▼─────────────▼──────────────▼────────────────────▼─────┐ │
│  │              详情页补全（发包单位/预算/开标时间/截止时间）      │ │
│  └─────────────────────────────┬───────────────────────────────┘ │
└────────────────────────────────┼────────────────────────────────┘
                                 │ 各自独立 .db
┌────────────────────────────────▼────────────────────────────────┐
│                       【存储层】                                  │
│                                                                  │
│  sufu.db  jszbcg.db  yancheng_gov.db  ycggzy.db  ...           │
│  每个 DB 内：notices 主表（全列）+ enriched 补全表               │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                       【调度层】                                  │
│                                                                  │
│  每 5 分钟：增量采集 → 检测新条目 → 推送                         │
│  每日：全量采集 + 月报生成                                        │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                       【报告层】                                  │
│                                                                  │
│  实时推送（飞书/TBD）   县区维度报告   月报 PDF   Web 看板(TBD)  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、公告类型（4 类全采）

| notice_type | 说明 | 核心字段 |
|-------------|------|---------|
| `tender` | 招标公告 | 开标时间、报名截止时间、预算金额 |
| `intention` | 采购意向 / 预算公告 | 预计挂网时间、概算金额 |
| `award` | 成交公告 / 中标通知 | 中标单位、中标金额 |
| `other` | 变更 / 更正 / 终止 / 其他 | 字段不固定 |

---

## 四、12 个网站采集规划

| # | 网站 | 简称 | 采集方式 | 当前 notice_type | Pro 补充 | 全域改造 |
|---|------|------|---------|-----------------|---------|---------|
| 1 | 盐城市政府采购网 | yancheng_gov | columnid API | 已有 15 栏（含成交/意向） | 补详情页关键字段 | 移除区县过滤 |
| 2 | 苏服采 | sufu | POST API | 仅 serviceType=1 | 加 serviceType=2,3... | 改为全盐城市 areaCode |
| 3 | 盐城市公共资源交易网 | ycggzy | Playwright+API | 招标计划/招标公告 | 加成交/中标结果 | 移除 areaCode 过滤 |
| 4 | 江苏招标采购服务平台 | jszbcg | GET API | bulletinType=1 | 加 type=2,3,4... | regionCode=3209 已是全域 |
| 5 | 城南新区公共资源交易网 | chennan | HTML | 招标公告 | 加成交/意向栏目 | 本站无需区域过滤 |
| 6 | 开发区公共资源交易网 | kaifaqu | HTML | 招标公告 | 加成交/意向栏目 | 本站无需区域过滤 |
| 7 | 盐城市大数据集团 | bigdata | HTML | 招标公告 | 加成交通知 | 本站无需区域过滤 |
| 8 | 盐城市都市建设投资集团 | dushi | HTML | 招标公告 | 加成交通知 | 本站无需区域过滤 |
| 9 | 盐城市东方集团 | dongfang | HTML | 招标公告 | 加成交通知 | 本站无需区域过滤 |
| 10 | 江苏世纪新城 | jscn | HTML | 招标公告 | 加成交通知 | 本站无需区域过滤 |
| 11 | 经开城发集团 | jingkai | HTML | 招标公告 | 加成交通知 | 本站无需区域过滤 |
| 12 | 悦达集团 | yueda | HTML | 招标公告 | 加成交通知 | 本站无需区域过滤 |

---

## 五、数据库设计

### 每网站独立 DB：`data/{site_key}.db`

**主表：`notices`（统一核心字段 + 全量原始数据）**

```sql
CREATE TABLE notices (
    -- 主键与来源
    id          TEXT PRIMARY KEY,          -- md5(project_name+publish_date+site)
    site        TEXT NOT NULL,             -- 网站简称
    notice_type TEXT NOT NULL,             -- tender/intention/award/other
    source_url  TEXT,                      -- 列表页URL
    detail_url  TEXT,                      -- 详情页URL

    -- 时间
    publish_date  DATE,
    crawl_time    DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 核心业务字段（所有类型共用，允许 NULL）
    project_name  TEXT NOT NULL,
    budget        REAL,
    budget_text   TEXT,
    budget_unit   TEXT,

    -- 发包方
    purchaser     TEXT,                    -- 发包单位（详情页补全）
    purchaser_raw TEXT,                    -- API 原始字段

    -- 类型专有字段（NULL 表示不适用）
    open_date     DATETIME,                -- 开标时间（tender）
    deadline      DATETIME,                -- 报名截止时间（tender）
    expected_list DATE,                    -- 预计挂网时间（intention）
    winner        TEXT,                    -- 中标单位（award）
    winning_amount REAL,                   -- 中标金额（award）

    -- 地域
    region        TEXT,                    -- 县区（盐城市全域，不过滤）
    district_code TEXT,                    -- 区县代码

    -- 原始数据（全列备份，任何 API 字段都不丢失）
    raw_json      TEXT,                    -- JSON dump of full API response record

    -- 状态
    detail_fetched INTEGER DEFAULT 0,      -- 0=未补全 1=已补全 2=补全失败
    is_duplicate  INTEGER DEFAULT 0
);

CREATE INDEX idx_publish_date  ON notices(publish_date);
CREATE INDEX idx_notice_type   ON notices(notice_type);
CREATE INDEX idx_region        ON notices(region);
CREATE INDEX idx_detail_fetch  ON notices(detail_fetched);
```

---

## 六、详情页补全策略

补全任务在采集后异步执行（或同步，取决于速率限制）：

```
采集列表 → 入库（detail_fetched=0）
    └→ 补全队列：扫 detail_fetched=0 的条目
           └→ 请求 detail_url
                  └→ 解析：发包单位 / 预算 / 开标时间 / 截止时间 / 预计挂网时间
                         └→ UPDATE notices SET ... detail_fetched=1
```

反爬处理：
- 请求间隔 0.5-1.5s 随机
- 失败重试 3 次，超过标记 detail_fetched=2（跳过，不阻塞主采集）

---

## 七、开发阶段规划

### Phase 1（2026-06-17 完成）：采集框架 + API 类网站 + 6 月数据
- [x] 项目全景图（PROJECT.md v0.2）
- [x] `crawlers/base.py` — 统一基础类、per-site DB、notice_type、raw_json
- [x] `crawlers/jszbcg.py` — 江苏招标采购服务平台（bulletinType 1/2/3/4/6，462条）
- [x] `crawlers/yancheng_gov.py` — 政府采购网（15 栏全采，294条）
- [x] `migrate_from_old.py` — 旧 history.db → Pro 各站 DB 迁移脚本
- [x] 6 月全量采集完成，12 站独立 DB 建立，合计 923 条
- [ ] `crawlers/sufu.py` — 苏服采（API 端口 868 今日超时，待单独补）
- [ ] `crawlers/ycggzy.py` — 公共资源交易网（Playwright，待 Phase 2）
- [ ] `run_collection.py` — 主采集入口（统一调度各站 Pro 采集器）

### Phase 2（待排期）：HTML 类网站
- [ ] 城南新区、开发区、大数据集团、都市建设、东方集团、世纪新城、经开城发、悦达集团
- [ ] 各站加成交/意向栏目

### Phase 3（待排期）：实时调度
- [ ] 5 分钟增量采集
- [ ] 飞书推送新条目
- [ ] 开标信息实时推送

### Phase 4（待排期）：报告与 Web
- [ ] 县区维度报告
- [ ] 月报 PDF 适配
- [ ] Web 看板（技术栈 TBD）

---

## 八、项目目录结构

```
~/.openclaw/workspace/yancheng-bidding-pro/
├── PROJECT.md                    # 本文件（项目全景图）
├── data/                         # 数据库文件
│   ├── sufu.db
│   ├── jszbcg.db
│   ├── yancheng_gov.db
│   ├── ycggzy.db
│   └── ...
├── crawlers/
│   ├── base.py                   # 基础类（DB管理 + 基础爬虫）
│   ├── sufu.py                   # 苏服采
│   ├── jszbcg.py                 # 江苏招标采购服务平台
│   ├── yancheng_gov.py           # 盐城市政府采购网
│   ├── ycggzy.py                 # 盐城市公共资源交易网（Playwright）
│   ├── chennan.py                # 城南新区公共资源交易网
│   ├── kaifaqu.py                # 开发区公共资源交易网
│   ├── bigdata.py                # 盐城市大数据集团
│   ├── dushi.py                  # 都市建设投资集团
│   ├── dongfang.py               # 东方集团
│   ├── jscn.py                   # 江苏世纪新城
│   ├── jingkai.py                # 经开城发集团
│   └── yueda.py                  # 悦达集团
├── run_collection.py             # 主采集入口（全量 / 增量 / 单站）
├── enrich_details.py             # 详情页补全（独立运行）
└── logs/
```

---

## 九、待确认项

- [ ] 苏服采 serviceType 取值（除 1=招标 外，成交/意向对应哪个值）
- [ ] 盐城市公共资源交易网成交/中标子分类 subcode
- [ ] 5 分钟推送渠道（飞书群/DM/网站）
- [ ] Web 前端技术栈与时间
- [ ] 数据库是否保持 SQLite（单机） or 升级为 PostgreSQL（高并发查询）
- [ ] 其他报告需求（用户仍在补充）

---

*最后更新：2026-06-17 Phase 1 开发中*

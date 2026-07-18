# yancheng-bidding-pro 数据模型 ER 图

> **版本**：v1.0  
> **生成日期**：2026-07-18  
> **审计依据**：GB/T 36073-2018 DCMM 数据架构域  
> **配套文档**：`docs/data_dictionary.md`

---

## 一、整体数据架构图

```
┌────────────────────────────────────────────────────────────────┐
│                        【采集层】13 站点                          │
│ jszbcg, yancheng_gov, ycggzy, sufu, yueda, dushi, jscn,        │
│ chennan, dongfang, bigdata, jingkai, kaifaqu, tyc              │
└──────────────────────────┬─────────────────────────────────────┘
                           ↓ (12 个 crawlers/*.py)
┌────────────────────────────────────────────────────────────────┐
│               【存储层 1】13 站点独立 DB                          │
│ data/{site}.db (每个 DB 含 notices + failed_records 表)         │
└──────────────────────────┬─────────────────────────────────────┘
                           ↓ (download_site_pages, enrich_*, 
                              add_std_*, extract_sme_target)
┌────────────────────────────────────────────────────────────────┐
│             【存储层 2】unified.db 归一化库                       │
│                                                                │
│  tender (4352)  ────┐                                          │
│  award (4961)   ────┼──→  project_links (3119)                │
│  intention (1286)───┤     ├─ tender_id ──→ tender.id          │
│  other (3866)   ────┘     └─ award_id  ──→ award.id           │
│                                                                │
│  + unified_audit (0)  ← 字段级变更审计                          │
│  + feedback (0)       ← 用户反馈闭环                            │
└──────────────────────────┬─────────────────────────────────────┘
                           ↓ (verify_quality.py)
                       【质量门】
                           ↓ (4 份 PDF 生成)
┌────────────────────────────────────────────────────────────────┐
│                     【应用层】4 份 PDF                           │
│ output/盐开招标公告_YYYYMM.pdf                                   │
│ output/盐开开标倒计时报告_YYYYMMDD.pdf                            │
│ output/盐城通信运营商中标报告_YYYY-MM.pdf                         │
│ output/盐开采购意向报告_YYYYMM.pdf                                │
└──────────────────────────┬─────────────────────────────────────┘
                           ↓ (push-pdfs.sh v3.0)
                     【飞书群推送】
```

---

## 二、unified.db 表关系（ER 图）

```
┌──────────────────────────┐
│     tender               │
├──────────────────────────┤
│ id (PK)            TEXT  │
│ site_name          TEXT  │
│ std_district       TEXT  │
│ proj_major_cat     TEXT  │
│ proj_minor_cat     TEXT  │
│ publish_date       TEXT  │
│ project_name       TEXT  │
│ purchaser          TEXT  │
│ budget             REAL  │
│ open_date          TEXT  │
│ deadline           TEXT  │
│ detail_url         TEXT  │
│ sme_target         TEXT  │
└──────────────────────────┘
            │
            │ tender_id (FK to tender.id)
            │
            ▼
┌──────────────────────────┐         ┌──────────────────────────┐
│   project_links          │ N:1     │     award                │
├──────────────────────────┤─────────├──────────────────────────┤
│ tender_id (FK)     TEXT  │         │ id (PK)            TEXT  │
│ award_id  (FK)     TEXT  │◄────────┤ site_name          TEXT  │
│ canonical_name     TEXT  │         │ std_district       TEXT  │
│ match_type         TEXT  │         │ proj_major_cat     TEXT  │
│ amendment_count    INT   │         │ proj_minor_cat     TEXT  │
└──────────────────────────┘         │ publish_date       TEXT  │
                                      │ project_name       TEXT  │
                                      │ purchaser          TEXT  │
                                      │ winner             TEXT  │
                                      │ winning_amount     REAL  │
                                      │ detail_url         TEXT  │
                                      └──────────────────────────┘

┌──────────────────────────┐         ┌──────────────────────────┐
│   intention              │         │     other                │
├──────────────────────────┤         ├──────────────────────────┤
│ id (PK)            TEXT  │         │ id (PK)            TEXT  │
│ site_name          TEXT  │         │ site_name          TEXT  │
│ std_district       TEXT  │         │ notice_subtype     TEXT  │
│ proj_major_cat     TEXT  │         │ std_district       TEXT  │
│ proj_minor_cat     TEXT  │         │ proj_major_cat     TEXT  │
│ publish_date       TEXT  │         │ proj_minor_cat     TEXT  │
│ project_name       TEXT  │         │ publish_date       TEXT  │
│ purchaser          TEXT  │         │ project_name       TEXT  │
│ budget             REAL  │         │ purchaser          TEXT  │
│ expected_list      TEXT  │         │ detail_url         TEXT  │
│ detail_url         TEXT  │         └──────────────────────────┘
│ sme_target         TEXT  │
└──────────────────────────┘

┌──────────────────────────┐         ┌──────────────────────────┐
│   unified_audit          │         │     feedback            │
├──────────────────────────┤         ├──────────────────────────┤
│ audit_id (PK)    INTEGER │         │ feedback_id (PK) INTEGER │
│ ts               TEXT    │         │ ts               TEXT    │
│ table_name       TEXT    │         │ source           TEXT    │
│ record_id        TEXT    │         │ feishu_msg_id    TEXT    │
│ field_name       TEXT    │         │ sender           TEXT    │
│ old_value        TEXT    │         │ record_type      TEXT    │
│ new_value        TEXT    │         │ record_id        TEXT    │
│ op_type          TEXT    │         │ category         TEXT    │
│ source           TEXT    │         │ message          TEXT    │
│ trace_id         TEXT    │         │ status           TEXT    │
└──────────────────────────┘         │ resolver         TEXT    │
                                     │ resolved_at      TEXT    │
                                     └──────────────────────────┘
```

---

## 三、每站 .db 表关系（简化 ER）

```
┌──────────────────────────┐
│      notices             │
├──────────────────────────┤
│ id (PK)            TEXT  │
│ site               TEXT  │
│ site_name          TEXT  │
│ notice_type        TEXT  │
│ notice_type_raw    TEXT  │
│ notice_subtype     TEXT  │
│ title              TEXT  │
│ project_name       TEXT  │
│ purchaser          TEXT  │
│ agency             TEXT  │
│ winner             TEXT  │
│ budget             REAL  │
│ winning_amount     REAL  │
│ open_date          TEXT  │
│ deadline           TEXT  │
│ publish_date       TEXT  │
│ detail_url         TEXT  │  ← UNIQUE INDEX (jszbcg/yancheng_gov/tyc)
│ page_path          TEXT  │
│ pdf_path           TEXT  │
│ content            TEXT  │
│ raw_json           TEXT  │
│ section            TEXT  │
│ std_district       TEXT  │
│ proj_major_cat     TEXT  │
│ proj_minor_cat     TEXT  │
│ sme_target         TEXT  │
│ created_at         TEXT  │
│ updated_at         TEXT  │
└──────────────────────────┘
            │
            │ (每条 notices 可对应一条失败记录)
            │
            ▼
┌──────────────────────────┐
│   failed_records         │
├──────────────────────────┤
│ id (PK)        INTEGER   │
│ ts             TEXT      │
│ site           TEXT      │
│ raw_url        TEXT      │
│ raw_html       TEXT      │
│ error_msg      TEXT      │
│ retry_count    INTEGER   │
│ resolved       INTEGER   │
└──────────────────────────┘
```

---

## 四、关键关联关系

### 4.1 project_links 关联 tender × award

```
tender.id ←─────── project_links.tender_id
                        │
                        └─── project_links.award_id ──→ award.id
```

**关联率**：67.2%（3119 条 / (4352+4961) / 2）

**match_type**：
- `exact`：标准化项目名完全匹配
- `fuzzy`：相似度 ≥ 0.8
- `manual`：人工匹配

### 4.2 unified_audit 反向追溯

```
tender.id ←─────── unified_audit.record_id (WHERE table_name='tender')
award.id ←──────── unified_audit.record_id (WHERE table_name='award')
intention.id ←─── unified_audit.record_id (WHERE table_name='intention')
other.id ←──────── unified_audit.record_id (WHERE table_name='other')
```

记录每次 build_unified.py 跑的字段级变更。

### 4.3 feedback 关联任意表

```
feedback.record_id ←── tender.id OR award.id OR intention.id OR other.id
feedback.record_type ──→ 区分关联表
```

---

## 五、数据规模（2026-07-18 实测）

| 表/库 | 记录数 | 大小 |
|------|------|------|
| tender | 4352 | - |
| award | 4961 | - |
| intention | 1286 | - |
| other | 3866 | - |
| project_links | 3119 | - |
| unified.db | - | 8.0 MB |
| jszbcg.db | 4793 | 11 MB |
| ycggzy.db | 4555 | 142 MB |
| yancheng_gov.db | 3045 | 5.3 MB |
| 其他 10 站 | 5499 | ~3 MB |

**总原始记录**：15146 条 → 归一后 14465 条（去重 + 类型映射）

---

## 六、变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-18 | v1.0 | 初始版本（审计批号 小标-2026-07-18-数据治理 P2-1） |

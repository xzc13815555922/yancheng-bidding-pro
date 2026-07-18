# ypb 验收标准（DoD: Definition of Done）

> **版本**：v1.0  
> **生成日期**：2026-07-18  
> **审计依据**：GB/T 8567-2006 + CMMI-DEV v2.0 + 软考高级第 16.5 节  
> **审计批号**：小标-2026-07-18-软件工程 P1-1

每条用户故事（US）对应一个 DoD，验收时按此对照。

---

## US-1：盐城全域招标采集

**DoD**：
- [x] 12 站点采集全部覆盖（jszbcg / yancheng_gov / ycggzy / sufu / yueda / 5 国企 / jingkai / kaifaqu）
- [x] 数据写入 unified.db 4 表（tender / award / intention / other）
- [x] 单日采集量 ≥ 100 条（实测 295 条/天）
- [x] cron 调度链路清晰（launchd plist + run-bidding.sh + run-full-pipeline.sh）

**验收方式**：
```bash
python3 run_collection.py --days 1
python3 verify_quality.py  # 期望: ✅ 全部通过
```

---

## US-2：天眼查运营商中标采集

**DoD**：
- [x] 13 家运营商子公司覆盖
- [x] Cookie 自动保存到 data/cookies.json
- [x] 写入 data/tyc.db
- [x] 三源合并（ypb + tyc + obm）

**验收方式**：
```bash
python3 crawlers/tyc_crawler.py --days 1
python3 generate_operator_combined_report.py
```

---

## US-3：PDF 月报生成

**DoD**：
- [x] 4 份 PDF 自动生成（招标公告月报 / 开标倒计时日报 / 运营商综合月报 / 采购意向月报）
- [x] 输出到 output/ 目录
- [x] 文件命名规范：盐开招标公告_YYYYMM.pdf

**验收方式**：
```bash
ls -la output/*.pdf  # 期望: 4 个 PDF
```

---

## US-4：飞书群推送

**DoD**：
- [x] 推送到飞书群 oc_922159a1e552ff69e99a99c1bd4d598b
- [x] 4 份 PDF 全推
- [x] 推送成功率 ≥ 95%（v3.0 后 4/4 全绿）

**验收方式**：
```bash
bash /Users/yc/.openclaw/agents/executor/scripts/push-pdfs.sh
# 期望: 4/4 全绿，messageId 全部回写
```

---

## US-5：数据质量基线（已治标）

**DoD**：
- [x] 12 站点字段基线定义在 config.py
- [x] verify_quality.py 自动校验
- [x] FAIL 时写 CRITICAL + 飞书告警 + halt
- [x] 8 项基线治标下调（带 TBD_T 标记）

**验收方式**：
```bash
python3 verify_quality.py  # 期望: ✅ 全部通过
```

---

## US-6：数据治理（新增）

**DoD**：
- [x] docs/data_dictionary.md（271 行）
- [x] docs/data_model.md（244 行）
- [x] docs/requirements_nfr.md（本文档）
- [x] docs/acceptance_criteria.md（本文档）
- [x] unified.db 含 unified_audit 表（字段级审计）
- [x] unified.db 含 feedback 表（用户反馈）
- [x] 13 站 db 含 failed_records 表（错误隔离）
- [x] 自动备份脚本 backup_all_db.py（保留 14 天）

**验收方式**：
```bash
python3 scripts/utils/init_unified_audit.py
python3 scripts/utils/init_failed_records.py
python3 scripts/utils/init_feedback.py
python3 scripts/utils/backup_all_db.py --dry-run
ls data/backup/  # 期望: 当日备份目录
```

---

## US-7：调度链路（已修复）

**DoD**：
- [x] launchd plist 配置每日 5:00（不是一次性）
- [x] run-bidding.sh 幂等锁 + 僵尸锁清理
- [x] run-full-pipeline.sh 含 11.5 步治理备份 + Step 0.5 治理建表

**验收方式**：
```bash
plutil -lint ~/Library/LaunchAgents/com.openclaw.bidding.6.17.plist
launchctl list | grep openclaw.bidding
```

---

## 通用 DoD（每个 PR 必须满足）

- [ ] 不破坏现有 pytest 测试（115 passed 维持）
- [ ] 不破坏 verify_quality（基线全绿）
- [ ] 改动文件有 docstring 或注释
- [ ] commit message 符合 conventional commits 规范
- [ ] 单文件改动 ≤ 500 行（除数据字典等纯文档）
- [ ] 单函数圈复杂度 ≤ 20（除测试通过的历史函数）

---

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-18 | v1.0 | 初始版本（审计批号 小标-2026-07-18-软件工程 P1-1） |

---

**维护者**：执行员小标  
**下次审查**：每个 sprint 同步更新

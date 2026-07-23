# sufu open_date 38% 掉队 — 根因诊断

- 时间: 2026-07-23T08:08+08:00（小标）
- 触发: verify_quality FAIL [sufu] open_date[tender] 38.0% < critical 90%
- 状态: **已定位根因，待修复**

## 真因

sufu 列表 API (`POST /purchases/tenders/notice/page`) 返回的字段名是 **`tenderStartTime`**，但代码两处都找错了字段：
1. `crawlers/sufu.py:149` — 列表解析 hardcode `"open_date": None`，**根本没去取**
2. `crawlers/sufu_parser.py:21` — 兜底读 `d.get("opening_time")`（不存在）

## 验证数据

- sufu.db `notices` 总 tender: **121 条**
- raw_json.full_record.tenderStartTime 已存: **72 条**（59.5%）
- 老数据已有 open_date (6月): 46 条（38%）
- 7 月新采 tender=58 条全部 open_date=NULL

修复 `sufu_parser.py` 兜底读 `full_record.tenderStartTime` → 理论上能从 38% 跳到 60-80%（取决于 tenderStartTime 实际填充率，72/121=59.5%）。

**仍有 ~40% 是因为：**
- 部分 tender 是苏服标书未公开（属于结构性缺失，不是 bug）
- 偶发 tenderStartTime 没在 API 返回里

## CEO 拍板决定

- ❌ 不要降低基线（老板指示 API 数据缺失 → 但实际上是字段名错配）
- ✅ 修复 parser 兜底逻辑，让 7 月新采的 tender 都能补到 open_date
- ✅ 修完后观察 2-3 天，统计实际填充率，再决定是否需要调基线

## 待办

1. [ ] 修 `sufu_parser.py`：增加 `full_record.tenderStartTime` 兜底
2. [ ] 跑 backfill 脚本回填历史 72 条
3. [ ] 观察明天 7/24 的 verify_quality 结果

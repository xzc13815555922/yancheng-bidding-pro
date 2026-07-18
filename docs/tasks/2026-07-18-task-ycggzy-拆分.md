# 任务工单：拆 _parse_ycggzy_content 高复杂度函数

**工单 ID**：TASK-2026-07-18-001  
**派发人**：小标（执行员）  
**执行人**：阿明（程序员）  
**来源**：CEO 阿泽 2026-07-18 09:08 拍板「拆函数要做」  
**截止日期**：2026-08-01（含测试覆盖完成）  
**关联**：软件工程审计 P0-2（小标-2026-07-18-P0 批号）

---

## 一、任务背景

`crawlers/ycggzy.py::_parse_ycggzy_content(html: str, notice_type: str)` 当前 **圈复杂度 = 91**（远超阈值 20），是 ypb 项目第二高复杂度函数（仅次于已拆完的 `parse_html_detail` 106→1）。

```
[FAIL] 290:0::parse_html_detail CC=71  ← 已拆为 _extract_purchaser (24) + _extract_budget (13)
[FAIL] crawlers/ycggzy.py::_parse_ycggzy_content CC=91  ← 本工单目标
```

---

## 二、任务目标

将 `_parse_ycggzy_content` 拆分为 **3-5 个职责单一的子函数**，使每个子函数 **CC ≤ 20**。

---

## 三、必做前置：补充测试覆盖

⚠️ **必须先补测试**，再动手拆代码——否则没有保护网，拆分会引入解析差异。

### 3.1 现状调查
- 现有 `tests/test_ycggzy.py` 覆盖度
- 现有 `tests/test_crawlers/` 是否有 ycggzy 测试

### 3.2 至少补充 8 个测试用例
- 至少覆盖：政府采购公告 / 中标公告 / 意向公告 / 更正公告 各 2 个

每个测试用例须锁定当前行为（输入 HTML → 期望输出 dict），作为拆分前后行为对比基准。

---

## 四、拆分方案（建议）

参考本次 `parse_html_detail` 拆分的成功经验（v7 最简方案：保持原缩进，搬到新函数体内），按 `_parse_ycggzy_content` 的内部职责分块：

```
_parse_ycggzy_content(html, notice_type)
  ├─ _extract_ycggzy_basic_info(html)         # 项目名称/编号/采购人
  ├─ _extract_ycggzy_budget(html)             # 预算金额
  ├─ _extract_ycggzy_dates(html)              # 开标/截止/公示日期
  └─ _extract_ycggzy_winner(html)             # 中标人（仅 award）
```

每个子函数 **签名一致**：`(html: str) -> Optional[xxx]`，主函数合并结果。

---

## 五、安全保证

1. **不改任何正则 / 字符串字面量 / 逻辑顺序**
2. **只移动代码 + 添加函数签名**
3. **每步验证**：
   - `bash -n crawlers/ycggzy.py` 通过
   - `python3 -m pytest tests/test_ycggzy.py -v` 全绿
   - `python3 -m pytest tests/ -q` 全绿（除 h5 历史黑洞）
   - `python3 scripts/utils/check_complexity.py` 报告此函数 CC ≤ 20
   - `python3 verify_quality.py` 全绿

---

## 六、参考样例

本次拆 `parse_html_detail` 的成功经验（v7 脚本 `/tmp/openclaw/refactor_parse_v7.py`）：
- **不需要 dedent**：原代码缩进 4/8/12 空格在新函数体内就是对的
- **保护网**：先在 `tests/test_enrich_details.py` 加 4 个行为锁定测试
- **每步验证**：跑 8 项质量门 + 全量 pytest + verify_quality
- **commit 信息格式**：`refactor(ycggzy): 拆 _parse_ycggzy_content CC=91→≤20（CEO 拍板）`

参考 commit：`fd50abe`（小标拆 parse_html_detail，本次工单的姊妹工单）

---

## 七、交付物

1. 修改后的 `crawlers/ycggzy.py`（含新子函数）
2. 补充的 `tests/test_ycggzy.py` 测试用例（≥ 8 个）
3. commit + push 到 `xzc13815555922/yancheng-bidding-pro.git`
4. 在本工单追加"完成报告"章节

---

## 八、8/1 截止前的里程碑

| 日期 | 里程碑 | 验证 |
|---|---|---|
| 7/22 | 测试覆盖 ≥ 8 个用例 | pytest 全绿 |
| 7/25 | 第一版拆分（draft） | check_complexity 报告 |
| 7/29 | 重构 + 验证 + commit | 8 项质量门 |
| 8/1 | push 到 GitHub | remote hash 一致 |

---

## 九、任务来源批号

**审计批号**：小标-2026-07-18-软件工程  
**关联 PM 需求**：无（直接执行 CEO 拍板）  
**优先级**：P0（CEO 9:08 拍板执行）

---

_工单创建时间：2026-07-18 09:14  
任务状态：🔴 待阿明接手  
工单 owner：小标（executor）  
阿明 session key：`agent:programmer:feishu:direct:ou_b35d7016cbf059314697a07bece773c2`_
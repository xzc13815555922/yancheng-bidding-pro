#!/usr/bin/env python3
"""
expand_intention.py — yancheng_gov 批次意向公告展开

将每条意向公告页面中的表格解析为子项目列表，写入 notices.expected_list（JSON）。
build_unified.py 在构建 unified.db 时会把多项批次展开为独立的 intention 记录。

用法:
  python3 expand_intention.py           # 处理 yancheng_gov 全部意向公告
  python3 expand_intention.py --dry-run # 仅统计，不写库
  python3 expand_intention.py --limit 20
"""
import argparse
import json
import re
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DATA_DIR / "yancheng_gov.db"

# 从管道分隔的 markdown 表格行提取子项
# 格式: | {seq} | {项目名} | {概况} | {预算万元} | {预计月份} | ...
ITEM_PAT = re.compile(
    r"\|\s*(\d+)\s*\|\s*([^|]{5,80}?)\s*\|\s*([^|]{2,}?)\s*\|\s*([\d,. ]+)\s*\|\s*(\d{4}-\d{2})"
)


def parse_intention_page(content: str) -> list[dict]:
    """从 markdown 页面提取意向子项列表。"""
    pipe_lines = [l for l in content.split("\n") if "|" in l and "---" not in l]
    combined = "|".join(pipe_lines)
    items = []
    for m in ITEM_PAT.finditer(combined):
        budget_str = m.group(4).replace(",", "").replace(" ", "").strip()
        try:
            budget_wan = float(budget_str)
        except ValueError:
            budget_wan = None
        items.append({
            "seq":            int(m.group(1)),
            "name":           m.group(2).strip(),
            "description":    m.group(3).strip(),
            "budget_wan":     budget_wan,
            "budget_yuan":    budget_wan * 10000 if budget_wan is not None else None,
            "expected_month": m.group(5).strip(),
        })
    return items


def run(dry_run: bool = False, limit: int = 0):
    if not DB_PATH.exists():
        print("yancheng_gov.db 不存在")
        return

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT id, project_name, page_path, budget, purchaser
        FROM notices WHERE notice_type='intention' AND page_path IS NOT NULL
    """).fetchall()

    if limit:
        rows = rows[:limit]

    total = parsed = multi = skipped = 0
    updates = []

    for row_id, name, pp, budget, purchaser in rows:
        total += 1
        p = Path(pp)
        if not p.exists():
            skipped += 1
            continue

        content = p.read_text(errors="ignore")
        items = parse_intention_page(content)
        if not items:
            skipped += 1
            continue

        parsed += 1
        if len(items) > 1:
            multi += 1

        # 若只有 1 项且 name 与 notice 标题相同，直接设 budget 不写 expected_list
        # （避免 build_unified 展开时重复）
        if len(items) == 1 and items[0]["name"] in name:
            # 只修正 budget 为更精确的子项预算
            if items[0]["budget_yuan"] is not None:
                updates.append((None, items[0]["budget_yuan"], row_id))
            else:
                updates.append((None, budget, row_id))
            continue

        elist_json = json.dumps(items, ensure_ascii=False)
        # budget 更新为所有子项合计
        total_yuan = sum(
            i["budget_yuan"] for i in items if i["budget_yuan"] is not None
        )
        updates.append((elist_json, total_yuan or budget, row_id))

    print(f"意向公告: {total}条  可解析: {parsed}  多项批次: {multi}  跳过: {skipped}")
    print(f"待写入: {len(updates)} 条")

    if not dry_run and updates:
        conn.executemany(
            "UPDATE notices SET expected_list=?, budget=? WHERE id=?", updates
        )
        conn.commit()
        print(f"已写入 {len(updates)} 条")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="yancheng_gov 意向公告子项解析")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不写库")
    parser.add_argument("--limit", type=int, default=0, help="最多处理条数")
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()

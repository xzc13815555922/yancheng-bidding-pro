#!/usr/bin/env python3
"""
将 data/pages/{site}/ 下的 MD 文件从 {id}.md 重命名为 {project_name}.md
同步更新各站 DB 中的 page_path。

命名规则：
  - project_name 前 60 字
  - 非法字符 / \\ : * ? " < > | 替换为 _
  - 去掉首尾空格及连续下划线
  - 重名时追加 _2 _3 ...
"""
import re
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
PAGE_DIR  = DATA_DIR / "pages"

SITES = [
    "yancheng_gov", "yueda", "dongfang", "dushi",
    "jscn", "chennan", "kaifaqu", "bigdata", "jingkai",
]

_ILLEGAL = re.compile(r'[/\\:*?"<>|]')
_MULTI_  = re.compile(r'_+')


def safe_name(title: str) -> str:
    t = title.strip()[:60]
    t = _ILLEGAL.sub('_', t)
    t = _MULTI_.sub('_', t).strip('_')
    return t or "unnamed"


def rename_site(site: str):
    db_path  = DATA_DIR / f"{site}.db"
    site_dir = PAGE_DIR / site
    if not site_dir.exists():
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, project_name, page_path FROM notices WHERE page_path IS NOT NULL"
    ).fetchall()

    used: dict[str, int] = {}  # safe_name → count for dedup
    renamed = skipped = 0

    for row in rows:
        rid      = row["id"]
        old_path = Path(row["page_path"])
        title    = row["project_name"] or rid

        base = safe_name(title)
        if base in used:
            used[base] += 1
            base = f"{base}_{used[base]}"
        else:
            used[base] = 1

        new_path = site_dir / f"{base}.md"

        if old_path == new_path:
            skipped += 1
            continue

        if not old_path.exists():
            # 文件已不存在（可能已手动改过），直接更新 DB
            conn.execute("UPDATE notices SET page_path=? WHERE id=?", (str(new_path), rid))
            skipped += 1
            continue

        if new_path.exists():
            # 目标已存在，用 _old_id 作后缀
            new_path = site_dir / f"{base}_{rid[:8]}.md"

        old_path.rename(new_path)
        conn.execute("UPDATE notices SET page_path=? WHERE id=?", (str(new_path), rid))
        renamed += 1

    conn.commit()
    conn.close()
    print(f"[{site}] 重命名={renamed}  跳过={skipped}")


def main():
    for site in SITES:
        rename_site(site)
    total = sum(len(list((PAGE_DIR / s).glob("*.md")))
                for s in SITES if (PAGE_DIR / s).exists())
    print(f"\n完成，共 {total} 个 MD 文件")


if __name__ == "__main__":
    main()

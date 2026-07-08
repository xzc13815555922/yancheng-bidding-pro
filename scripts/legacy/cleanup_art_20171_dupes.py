#!/usr/bin/env python3
"""
cleanup_art_20171_dupes.py — 清理 unified.db / yancheng_gov.db 里 columnid=20171 的脏数据

背景：
- czj.yancheng.gov.cn 的 columnid=20171 栏目实际是「公开招标公告的精简跳转页」，
  不是真需求公示。同一个项目会同时出现在 20171（跳转页）和 20174/20176/20177/...
  等完整公告页。
- 后果：art_20171_* 的 66 条在 unified.db.tender 表里 open_date 全空（详情页无开标时间字段），
  且 make_id(title, publish_date, site) 去重没生效（两条 URL 标题文本不完全相同）。

用法：
    # 默认 dry-run，只统计和打印样例，不真删
    python3 cleanup_art_20171_dupes.py

    # 真正执行删除（先备份，再删）
    python3 cleanup_art_20171_dupes.py --confirm

回退：
    备份在 data/backup/<日期>/<时间戳>/，把 unified.db / yancheng_gov.db 覆盖回去即可
"""
import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
BACKUP_DIR = DATA_DIR / "backup"
UNIFIED_DB = DATA_DIR / "unified.db"
YANCHENG_GOV_DB = DATA_DIR / "yancheng_gov.db"

# 脏数据识别：URL 里含 art_20171 (columnid=20171 的栏目产物)
ART_20171_PATTERN = "%art_20171%"


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _backup(db_path: Path, stamp_dir: Path) -> Path:
    """复制 db 到 backup 目录。返回备份文件路径。"""
    if not db_path.exists():
        return None
    stamp_dir.mkdir(parents=True, exist_ok=True)
    dst = stamp_dir / db_path.name
    shutil.copy2(db_path, dst)
    # WAL/SHM 一起备份（避免备份点不一致）
    for ext in ("-wal", "-shm"):
        src = db_path.with_name(db_path.name + ext)
        if src.exists():
            shutil.copy2(src, dst.with_name(dst.name + ext))
    return dst


def _list_dirty_unified(conn: sqlite3.Connection) -> list:
    """列出 unified.db.tender 里 detail_url 含 art_20171 的所有条目"""
    rows = conn.execute(
        f"SELECT id, project_name, publish_date, detail_url "
        f"FROM tender WHERE detail_url LIKE ? ORDER BY publish_date DESC",
        (ART_20171_PATTERN,),
    ).fetchall()
    return [dict(r) for r in rows]


def _list_dirty_yancheng(conn: sqlite3.Connection) -> list:
    """列出 yancheng_gov.db.notices 里 notice_type=requirement 的所有条目"""
    rows = conn.execute(
        "SELECT id, notice_type, project_name, publish_date, detail_url "
        "FROM notices WHERE notice_type = 'requirement' ORDER BY publish_date DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _print_samples(items: list, label: str, n: int = 5):
    print(f"\n[{label}] 样例 {min(n, len(items))} 条:")
    for it in items[:n]:
        # 截 detail_url 显示（太长影响可读性）
        url = it.get("detail_url", "") or ""
        if len(url) > 80:
            url = url[:77] + "..."
        print(f"  - {it.get('publish_date', '')} | {it.get('project_name', '')[:60]}")
        print(f"      url: {url}")
        print(f"      id:  {it.get('id', '')[:16]}...")


def main():
    ap = argparse.ArgumentParser(description="清理 columnid=20171 产生的脏数据")
    ap.add_argument(
        "--confirm", action="store_true",
        help="真正执行删除（默认 dry-run）",
    )
    ap.add_argument(
        "--samples", type=int, default=5,
        help="打印样例条数（默认 5）",
    )
    args = ap.parse_args()

    if not UNIFIED_DB.exists():
        print(f"❌ 找不到 {UNIFIED_DB}，请在 yancheng-bidding-pro 根目录跑")
        sys.exit(1)
    if not YANCHENG_GOV_DB.exists():
        print(f"❌ 找不到 {YANCHENG_GOV_DB}")
        sys.exit(1)

    print("=" * 70)
    print(f" cleanup_art_20171_dupes.py — 清理 columnid=20171 脏数据")
    print(f" 模式: {'【真删 CONFIRM】' if args.confirm else '【DRY-RUN，不删】'}")
    print(f" 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1) 列出脏数据
    u_conn = _open(UNIFIED_DB)
    y_conn = _open(YANCHENG_GOV_DB)

    dirty_unified = _list_dirty_unified(u_conn)
    dirty_yancheng = _list_dirty_yancheng(y_conn)

    print(f"\n📊 统计:")
    print(f"  unified.db.tender  (detail_url LIKE '%art_20171%') : {len(dirty_unified)} 条")
    print(f"  yancheng_gov.db.notices (notice_type='requirement') : {len(dirty_yancheng)} 条")

    if not dirty_unified and not dirty_yancheng:
        print("\n✅ 无脏数据，无需清理")
        u_conn.close()
        y_conn.close()
        return

    _print_samples(dirty_unified, "unified.db.tender (art_20171)", args.samples)
    _print_samples(dirty_yancheng, "yancheng_gov.db.notices (requirement)", args.samples)

    # 2) Dry-run 模式下直接退出
    if not args.confirm:
        print("\n" + "-" * 70)
        print(" DRY-RUN 结束。未做任何修改。")
        print(" 跑 `python3 cleanup_art_20171_dupes.py --confirm` 真删（会自动备份）。")
        u_conn.close()
        y_conn.close()
        return

    # 3) 真删：先备份
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_dir = BACKUP_DIR / stamp
    print(f"\n🔄 备份到: {backup_dir}")
    bk_u = _backup(UNIFIED_DB, backup_dir)
    bk_y = _backup(YANCHENG_GOV_DB, backup_dir)
    print(f"  ✅ {bk_u}")
    print(f"  ✅ {bk_y}")

    # 4) 真删
    deleted_u = 0
    if dirty_unified:
        cur = u_conn.execute(
            f"DELETE FROM tender WHERE detail_url LIKE ?", (ART_20171_PATTERN,)
        )
        deleted_u = cur.rowcount
        u_conn.commit()
    print(f"\n🗑️  unified.db.tender  删除 {deleted_u} 条")

    deleted_y = 0
    if dirty_yancheng:
        cur = y_conn.execute(
            "DELETE FROM notices WHERE notice_type = 'requirement'"
        )
        deleted_y = cur.rowcount
        y_conn.commit()
    print(f"🗑️  yancheng_gov.db.notices 删除 {deleted_y} 条")

    u_conn.close()
    y_conn.close()

    print("\n" + "=" * 70)
    print(f" ✅ 完成。共删除 {deleted_u + deleted_y} 条脏数据")
    print(f" 回退: cp {backup_dir}/*.db {DATA_DIR}/")
    print("=" * 70)


if __name__ == "__main__":
    main()
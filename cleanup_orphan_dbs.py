#!/usr/bin/env python3
"""
cleanup_orphan_dbs.py
=====================

扫描 data/*.db 找出 0 字节残留文件,自动备份到 data/backup/orphan_dbs/ 后删除。

用法:
    python3 cleanup_orphan_dbs.py            # 交互模式(需 y/N 确认)
    python3 cleanup_orphan_dbs.py --yes      # 跳过确认,直接执行
    python3 cleanup_orphan_dbs.py --dry-run  # 只扫描,不删

退出码:
    0  成功(无孤儿或已清理)
    1  用户取消
    2  执行异常
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ---------- 路径常量 ----------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = DATA_DIR / "backup" / "orphan_dbs"
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "cleanup_orphan_dbs.log"


def log(msg: str) -> None:
    """打印并写日志。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"⚠️  日志写入失败: {e}", file=sys.stderr)


def find_orphan_dbs(data_dir: Path) -> list[Path]:
    """扫描 data_dir 下的 0 字节 *.db 文件。"""
    if not data_dir.exists():
        return []
    return [
        p for p in sorted(data_dir.glob("*.db"))
        if p.is_file() and p.stat().st_size == 0
    ]


def confirm(prompt: str) -> bool:
    """交互式 y/N 确认。"""
    try:
        ans = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans in ("y", "yes")


def cleanup(yes: bool = False, dry_run: bool = False) -> int:
    log(f"=== 开始扫描孤儿 DB | dry_run={dry_run} yes={yes} ===")

    orphans = find_orphan_dbs(DATA_DIR)
    if not orphans:
        log("✅ 未发现 0 字节 DB,无需清理。")
        return 0

    print()
    print(f"⚠️  将删除 {len(orphans)} 个 0 字节 DB:")
    for p in orphans:
        print(f"   - {p.name} ({p.stat().st_size} 字节)")
    print(f"备份目录: {BACKUP_DIR.relative_to(PROJECT_ROOT)}")
    print()

    if dry_run:
        log(f"[DRY-RUN] 跳过实际删除,共 {len(orphans)} 个候选。")
        return 0

    if not yes and not confirm("确认删除以上文件? [y/N]: "):
        log("❌ 用户取消,未做任何变更。")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    success, failed = 0, 0

    for p in orphans:
        try:
            backup_name = f"{p.stem}.{ts_tag}{p.suffix}"
            backup_path = BACKUP_DIR / backup_name
            shutil.copy2(p, backup_path)
            p.unlink()
            log(f"✅ 已备份并删除: {p.name} -> {backup_path.relative_to(PROJECT_ROOT)}")
            success += 1
        except OSError as e:
            log(f"❌ 处理失败: {p.name} ({e})")
            failed += 1

    log(f"=== 清理完成 | 成功 {success} | 失败 {failed} ===")
    return 0 if failed == 0 else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="清理 data/ 下 0 字节孤儿 SQLite 文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="跳过确认,直接执行删除",
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="只扫描报告,不实际删除",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return cleanup(yes=args.yes, dry_run=args.dry_run)
    except Exception as e:  # noqa: BLE001
        log(f"❌ 异常退出: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
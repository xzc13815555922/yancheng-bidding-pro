#!/usr/bin/env python3
"""
backup_all_db.py — 全 DB 自动备份脚本
依据 GB/T 36073-2018 DCMM 数据生存周期要求 + 治理审计 P1-存-2

功能：
  1. 用 sqlite3 .backup API（一致性快照，无锁冲突）
  2. 备份到 data/backup/YYYYMMDD/ 目录
  3. 保留最近 14 天（自动清理）
  4. 支持 dry-run 预览
  5. 备份完返回 0；失败返回非 0（不阻塞 pipeline）

用法：
  python3 scripts/utils/backup_all_db.py                # 实际备份
  python3 scripts/utils/backup_all_db.py --dry-run      # 仅显示会备份什么
  python3 scripts/utils/backup_all_db.py --keep 7       # 自定义保留天数

设计原则（不动现有流程）：
  - 仅新增 scripts/utils/ 下脚本
  - 不修改 run-full-pipeline.sh（CEO 后续决定是否接入）
  - 不修改现有 cron（同样原因）
  - 先发布为可选工具，让 PM/CEO 决定是否挂 cron
"""
import argparse
import shutil
import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

PROJ_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = PROJ_DIR / "data"
BACKUP_ROOT = DATA_DIR / "backup"


def list_target_dbs():
    """列出所有待备份的 .db 文件（含 shm/wal 配套文件）"""
    targets = []
    for db_file in sorted(DATA_DIR.glob("*.db")):
        if db_file.name in {"unified.db"}:
            targets.append(db_file)
            for ext in (".db-shm", ".db-wal"):
                companion = db_file.with_name(db_file.name + ext)
                if companion.exists():
                    targets.append(companion)
        else:
            # 站点 DB（除 unified 外的所有 .db）
            targets.append(db_file)
            for ext in (".db-shm", ".db-wal"):
                companion = db_file.with_name(db_file.name + ext)
                if companion.exists():
                    targets.append(companion)
    return targets


def get_total_size(files):
    return sum(f.stat().st_size for f in files)


def cleanup_old_backups(keep_days: int, dry_run: bool = False) -> list[Path]:
    """清理超过 keep_days 天的备份目录"""
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = []
    if not BACKUP_ROOT.exists():
        return removed
    for sub in sorted(BACKUP_ROOT.iterdir()):
        if not sub.is_dir():
            continue
        try:
            dir_date = datetime.strptime(sub.name, "%Y%m%d")
        except ValueError:
            continue
        if dir_date < cutoff:
            if dry_run:
                print(f"  [dry-run] 会删除: {sub.name} (大小: {sum(f.stat().st_size for f in sub.rglob('*') if f.is_file())/1024:.1f} KB)")
            else:
                shutil.rmtree(sub)
                print(f"  🗑️  已删除过期备份: {sub.name}")
            removed.append(sub)
    return removed


def backup_all(keep_days: int = 14, dry_run: bool = False) -> int:
    today_str = datetime.now().strftime("%Y%m%d")
    backup_dir = BACKUP_ROOT / today_str
    targets = list_target_dbs()
    total_size = get_total_size(targets)

    print(f"📦 备份目标: {len(targets)} 个文件")
    print(f"📁 备份目录: {backup_dir}")
    print(f"💾 总大小:   {total_size/1024/1024:.2f} MB")
    print(f"📅 保留天数: {keep_days} 天")
    if dry_run:
        print(f"\n🔍 [DRY-RUN] 仅预览，不实际备份/清理")
        for f in targets:
            print(f"  → {f.relative_to(PROJ_DIR)} ({f.stat().st_size/1024:.1f} KB)")
        print()
        cleanup_old_backups(keep_days, dry_run=True)
        return 0

    if backup_dir.exists():
        print(f"⚠️  今日备份已存在: {backup_dir}")
        print(f"    跳过备份（保留现有），仅执行清理")
        cleanup_old_backups(keep_days)
        return 0

    backup_dir.mkdir(parents=True, exist_ok=True)
    success = 0
    failed = []
    for db_file in targets:
        dest = backup_dir / db_file.name
        try:
            if db_file.suffix == ".db":
                # 用 sqlite3 backup API（一致性快照，无锁冲突）
                src_conn = sqlite3.connect(str(db_file))
                dst_conn = sqlite3.connect(str(dest))
                with dst_conn:
                    src_conn.backup(dst_conn)
                src_conn.close()
                dst_conn.close()
            else:
                # shm/wal 配套文件直接拷贝
                shutil.copy2(db_file, dest)
            success += 1
            print(f"  ✅ {db_file.name} ({db_file.stat().st_size/1024:.1f} KB)")
        except Exception as e:
            failed.append((db_file.name, str(e)))
            print(f"  ❌ {db_file.name}: {e}")

    print()
    print(f"📊 备份结果: {success}/{len(targets)} 成功")
    if failed:
        for name, err in failed:
            print(f"  ⚠️ {name}: {err}")
        return 1

    # 清理过期备份
    cleanup_old_backups(keep_days)
    print()
    print(f"✅ 备份完成 → {backup_dir}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="ypb 全 DB 自动备份")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际备份")
    parser.add_argument("--keep", type=int, default=14, help="保留天数（默认 14）")
    args = parser.parse_args()
    return backup_all(keep_days=args.keep, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

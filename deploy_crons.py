#!/usr/bin/env python3
"""
deploy_crons.py — 一次性部署 (CEO 拍板后执行)

按老板最终需求 (2026-07-23 22:00):
  - 工作日 8 点一次跑 morning (采通 + PDF + 推群)
  - 工作日 9-20 点每小时一次 采通
  - 每天 7 点 tyc 天眼查
  - 周末 8 点一次采通 (但 run-morning.sh 周末会处理 PDF; 周末又要不跑?)
  - 老板原话: 周六周日 8:00 一次性采集/富化/通报 PDF
    → 周末也走 run-morning.sh (一致性, 比单独写好)

新增 cron (3 条):
  - ybp-tyc-daily     0 7 * * *         tyc
  - ybp-morning       0 8 * * *         采通 + PDF + 推群 (每天, 工作日和周末都跑)
  - ybp-collect-hourly  0 9-20 * * 1-5  整点采通 (工作日)

cron task 用 flock -n 包装, 防止重叠.

disable 老 cron (2 条, 不删, 留回滚):
  - cd8c4dbf 5:00 pipeline  (已迁移到 8:00 morning)
  - f605317e 8:35 push     (已并入 8:00 morning)
"""

import subprocess
import sys


def add_cron(name, expr, payload_cmd, timeout=900):
    """加一条 cron. payload_cmd 是 bash -c \"...\" 形式."""
    cmd = [
        "openclaw", "cron", "add",
        "--name", name,
        "--schedule", expr,
        "--tz", "Asia/Shanghai",
        "--session-target", "isolated",
        "--message", payload_cmd,
        "--timeout-seconds", str(timeout),
    ]
    print(f"\n[ADD] {name}: {expr}")
    print(f"  timeout={timeout}s")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"  rc={r.returncode}")
    if r.stdout: print(f"  stdout: {r.stdout[:500]}")
    if r.stderr: print(f"  stderr: {r.stderr[:500]}")
    return r.returncode


def disable_cron(job_id, label=""):
    cmd = ["openclaw", "cron", "update", "--job-id", job_id, "--enabled", "false"]
    print(f"\n[DISABLE] {job_id} ({label})")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"  rc={r.returncode}")
    if r.stdout: print(f"  stdout: {r.stdout[:300]}")
    if r.stderr: print(f"  stderr: {r.stderr[:300]}")


def main():
    YBP = "/Users/yc/.openclaw/workspace/yancheng-bidding-pro"

    # ── 1. tyc (7 点, 每天) ──
    add_cron(
        name="ybp-tyc-daily 7:00",
        expr="0 7 * * *",
        payload_cmd=f"/usr/bin/flock -n /tmp/openclaw/ybp-tyc.lock /bin/bash {YBP}/run-tyc.sh",
        timeout=1200,
    )

    # ── 2. morning (8 点, 每天) ──
    # weekend 跟 weekday 一样: 8 点采通 + PDF + 推群
    add_cron(
        name="ybp-morning 8:00 daily",
        expr="0 8 * * *",
        payload_cmd=f"/usr/bin/flock -n /tmp/openclaw/ybp-morning.lock /bin/bash {YBP}/run-morning.sh",
        timeout=1800,
    )

    # ── 3. collect-hourly (9-20 点, 工作日 1-5) ──
    add_cron(
        name="ybp-collect-hourly weekday 9-20",
        expr="0 9-20 * * 1-5",
        payload_cmd=f"/usr/bin/flock -n /tmp/openclaw/ybp-collect.lock /usr/bin/python3 {YBP}/incremental_collect.py --mode fast --no-wait",
        timeout=900,
    )

    # ── 4. disable 老的 2 条 ──
    print("\n" + "=" * 50)
    print("⚠️ disable 老 cron (rollback-safe, 只是 enabled=false)")
    disable_cron("cd8c4dbf-9327-48ac-a4a2-091810dadecf", "ybp daily 5:00 pipeline")
    disable_cron("f605317e-bb5c-4a0d-b605-efdc31a609b4", "ybp push 4 PDFs 8:35")

    print("\n" + "=" * 50)
    print("✅ 部署完成")
    print("\n验证: openclaw cron list | grep ybp")


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        print("🔍 DRY-RUN\n")
        print("会执行:")
        print("  + 3 个 cron: tyc/morning/collect-hourly")
        print("  - 2 个老 cron: cd8c4dbf 5:00 + f605317e 8:35")
        print("\n确认部署去掉 --dry-run 重跑.")
        sys.exit(0)
    main()

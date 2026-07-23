#!/usr/bin/env python3
"""
deploy_crons.py — 一次性部署脚本 (CEO 拍板后执行)

按老板需求 (2026-07-23):
  1. 增 4 个新 cron (tyc / pdf / collect-weekday / collect-weekend)
  2. disable 2 个老 cron (cd8c4dbf 5:00 大流程 / f605317e 8:35 推群)
  3. 不删老 cron, 留 rollback 路径

注意: OpenClaw cron 是 sessions_spawn 级别, 不需要 restart.
"""

import subprocess
import sys


def add(name, expr, msg, timeout=600):
    """调 openclaw cron add 加一条 cron 任务 (sessionTarget=isolated)."""
    cmd = [
        "openclaw", "cron", "add",
        "--name", name,
        "--schedule", expr,
        "--tz", "Asia/Shanghai",
        "--session-target", "isolated",
        "--message", msg,
        "--timeout-seconds", str(timeout),
    ]
    print(f"\n[ADD] {name}: {expr}")
    print(f"  timeout={timeout}s")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"  rc={r.returncode}")
    if r.stdout:
        print(f"  stdout: {r.stdout[:300]}")
    if r.stderr:
        print(f"  stderr: {r.stderr[:300]}")
    return r.returncode


def disable(job_id, name=""):
    """调 openclaw cron update 设 enabled=false."""
    cmd = ["openclaw", "cron", "update", "--job-id", job_id, "--enabled", "false"]
    print(f"\n[DISABLE] {job_id} ({name})")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"  rc={r.returncode}")
    if r.stdout:
        print(f"  stdout: {r.stdout[:300]}")


def main():
    # ─── 新增 4 条 cron ───
    # 1. tyc 天眼查, 每天 7 点, 7 天全勤
    add(
        name="ybp-tyc-daily 7:00",
        expr="0 7 * * *",
        msg="执行天眼查采集: bash /Users/yc/.openclaw/workspace/yancheng-bidding-pro/run-tyc.sh",
        timeout=1200,  # 20 分钟留 buffer
    )
    # 2. PDF 日报, 每天 8 点, 调用 run-daily-report.sh
    add(
        name="ybp-pdf-report 8:00",
        expr="0 8 * * *",
        msg="执行 PDF 日报: bash /Users/yc/.openclaw/workspace/yancheng-bidding-pro/run-daily-report.sh",
        timeout=1800,  # 30 分钟
    )
    # 3. 采集 + 通报 (工作日 8-20 每小时)
    add(
        name="ybp-collect-hourly weekday 8-20",
        expr="0 8-20 * * 1-5",
        msg="执行增量采集 + 群通报: python3 /Users/yc/.openclaw/workspace/yancheng-bidding-pro/incremental_collect.py --mode fast",
        timeout=900,  # 15 分钟
    )
    # 4. 采集 + 通报 (周末 8 点一次)
    add(
        name="ybp-collect-daily weekend 8:00",
        expr="0 8 * * 6,0",
        msg="执行增量采集 + 群通报: python3 /Users/yc/.openclaw/workspace/yancheng-bidding-pro/incremental_collect.py --mode fast",
        timeout=900,
    )

    # ─── 禁用 2 条老 cron ───
    print("\n" + "=" * 50)
    print("⚠️ 准备 disable 老 cron (rollback-safe, 只是 enabled=false)")
    disable("cd8c4dbf-9327-48ac-a4a2-091810dadecf", "ybp daily 5:00 全流程")
    disable("f605317e-bb5c-4a0d-b605-efdc31a609b4", "ybp push 4 PDFs 8:35")

    print("\n" + "=" * 50)
    print("✅ 部署完成")
    print("\n验证: openclaw cron list | grep ybp")


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        print("🔍 DRY-RUN 模式, 不实际执行\n")
        print("会执行以下操作:")
        print("1. 新增 4 条 cron (tyc / pdf / collect-weekday / collect-weekend)")
        print("2. disable 2 条老 cron (cd8c4dbf 5:00 + f605317e 8:35)")
        print("\n确认部署请去掉 --dry-run 后重跑:")
        print("  python3 deploy_crons.py")
        sys.exit(0)
    main()

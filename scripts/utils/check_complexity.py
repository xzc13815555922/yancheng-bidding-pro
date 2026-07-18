#!/usr/bin/env python3
"""
check_complexity.py — 代码圈复杂度治理检查（软件工程 P0-1）
依据 GB/T 8567-2006 + CMMI-DEV v2.0

功能：
  - 用 mccabe 检查 .py 文件圈复杂度
  - 阈值：函数 > 20 → 警告，函数 > 30 → 失败
  - 输出 Markdown 报告到 docs/code_complexity_report.md
  - exit 0（不阻塞 CI，仅警告）

设计原则：
  - 仅检查 + 报告，不改代码
  - 改动代码由开发者按报告人工修复
  - 与现有 6 个 test 文件完全独立
"""
import subprocess
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

PROJ_DIR = Path(__file__).resolve().parents[2]
REPORT_PATH = PROJ_DIR / "docs" / "code_complexity_report.md"
THRESHOLD_WARN = 20
THRESHOLD_FAIL = 30


def run_mccabe(targets):
    """调用 mccabe 检查"""
    result = subprocess.run(
        ["/usr/bin/python3", "-m", "mccabe", "--min", str(THRESHOLD_WARN), *targets],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def parse_mccabe_output(output):
    """解析 mccabe 输出为结构化数据
    mccabe 输出格式: 290:0: 'parse_html_detail' 106
    """
    findings = []
    import re
    pattern = re.compile(r"^(\d+):(\d+):\s*'([^']+)'\s+(\d+)$")
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            line_no, col, func_name, cc = m.groups()
            findings.append({
                "location": f"{line_no}:{col}",
                "function": func_name,
                "cc": int(cc),
                "level": "FAIL" if int(cc) >= THRESHOLD_FAIL else "WARN"
            })
    return findings


def generate_report(findings):
    """生成 Markdown 报告"""
    now = datetime.now(timezone.utc).isoformat()
    fail_count = sum(1 for f in findings if f["level"] == "FAIL")
    warn_count = sum(1 for f in findings if f["level"] == "WARN")

    md = [
        "# 代码复杂度报告",
        "",
        f"> 生成时间: {now}  ",
        f"> 检查工具: mccabe (Python)  ",
        f"> 警告阈值: CC > {THRESHOLD_WARN}  ",
        f"> 失败阈值: CC > {THRESHOLD_FAIL}  ",
        "",
        "## 概览",
        "",
        f"- **FAIL 函数**: {fail_count}",
        f"- **WARN 函数**: {warn_count}",
        f"- **总问题**: {fail_count + warn_count}",
        "",
        "## 问题清单（按复杂度降序）",
        "",
        "| 文件:行 | 函数 | CC | 等级 |",
        "|---------|------|----|----|",
    ]
    for f in sorted(findings, key=lambda x: -x["cc"]):
        md.append(f"| {f['location']} | `{f['function']}` | **{f['cc']}** | {f['level']} |")

    md.extend([
        "",
        "## 治理建议",
        "",
        f"- CC > {THRESHOLD_FAIL} 的函数必须拆分（FAIL）",
        f"- CC > {THRESHOLD_WARN} 的函数建议拆分（WARN）",
        "- 拆分方法：",
        "  - 提取 `if/elif` 链为策略模式（dict 映射）",
        "  - 提取 `try/except` 块为独立子函数",
        "  - 用 `match/case` (Python 3.10+) 替换长 if 链",
        "",
        "## 历史",
        "",
        f"- {now[:10]} v1.0 初始版本（审计批号 小标-2026-07-18-软件工程 P0-1）",
        "",
    ])
    return "\n".join(md)


def main():
    targets = [
        "enrich_details.py",
        "crawlers/ycggzy.py",
        "crawlers/jszbcg.py",
        "crawlers/sufu.py",
        "crawlers/tyc_crawler.py",
        "crawlers/yancheng_gov.py",
    ]
    print("🔍 圈复杂度检查中...")
    output = run_mccabe(targets)
    findings = parse_mccabe_output(output)

    if not findings:
        print("✅ 所有函数复杂度均在阈值内")
        REPORT_PATH.write_text(
            f"# 代码复杂度报告\n\n生成时间: {datetime.now(timezone.utc).isoformat()}\n\n✅ 全部通过（CC ≤ {THRESHOLD_WARN}）\n",
            encoding="utf-8"
        )
        return 0

    fail = [f for f in findings if f["level"] == "FAIL"]
    warn = [f for f in findings if f["level"] == "WARN"]

    print(f"⚠️  发现 {len(findings)} 个问题：FAIL={len(fail)}, WARN={len(warn)}")
    for f in sorted(findings, key=lambda x: -x["cc"])[:5]:
        print(f"  [{f['level']}] {f['location']}::{f['function']} CC={f['cc']}")

    report = generate_report(findings)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"📄 报告已生成: {REPORT_PATH}")
    # 不阻塞 CI
    return 0


if __name__ == "__main__":
    sys.exit(main())

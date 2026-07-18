#!/usr/bin/env python3
"""
watch_22hao.py — 盐政办发〔2025〕22号 正式版监控脚本

依据 CEO 2026-07-18 09:21 拍板：设置月度提醒等 2025 版印发后跟进。

策略（2026-07-18 现状）：
  - 2025 22 号 = 征求意见稿（2025-08-25 ~ 28 征求意见期）
  - 正式版印发后通常在「盐城市人民政府公报」/「规范性文件库」公开
  - yancheng.gov.cn 反爬 403 + JS 动态加载 → 主动探测不可靠
  - 备用：doc88.com / 江苏省政府门户 转载

使用方法：
  # 主动探测（每月自动跑，0 依赖）
  python3 watch_22hao.py --probe

  # 人工输入 URL 后验证（CEO 拿到链接后跑）
  python3 watch_22hao.py --url https://...

  # 标记正式版印发后写日志
  python3 watch_22hao.py --mark-published --url https://...

  # 查询历史
  python3 watch_22hao.py --history

输出：
  - /tmp/openclaw/policy_22hao_state.json   ← 当前状态
  - /tmp/openclaw/policy_22hao.log          ← 运行日志
  - stdout → 飞书推送用 markdown 摘要

退出码：
  - 0 = 未发布（继续监控）
  - 2 = 正式版已发布（CEO 拍板后续动作）
  - 1 = 探测失败（不影响调度）
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

STATE_FILE = Path("/tmp/openclaw/policy_22hao_state.json")
LOG_FILE = Path("/tmp/openclaw/policy_22hao.log")
PROBE_TARGETS = [
    # 主动探测（按可访问性排序）
    ("盐城市人民政府门户", "https://www.yancheng.gov.cn/col/col34073/index.html"),
    ("江苏省政府门户", "https://www.jiangsu.gov.cn/"),
    ("盐城市数据局公开页", "https://www.yancheng.gov.cn/col/col34073/index.html"),
]


def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}\n"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line)
    print(line.rstrip())


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {
        "policy_id": "盐政办发〔2025〕22号",
        "policy_name": "盐城市市级政务信息化项目建设管理办法",
        "status": "征求意见稿",
        "first_seen": "2026-07-18",
        "probe_history": [],
        "published_url": None,
        "published_at": None,
        "manual_urls": [],
        "last_probe_at": None,
        "version": "1.0",
    }


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def probe() -> dict:
    """主动探测多个渠道，返回探测结果"""
    results = []
    for name, url in PROBE_TARGETS:
        try:
            proc = subprocess.run(
                ["curl", "-s", "-m", "10", "-L",
                 "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                 "-o", "/dev/null", "-w", "%{http_code}", url],
                capture_output=True, text=True, timeout=15,
            )
            code = proc.stdout.strip()
            results.append({"channel": name, "url": url, "status_code": code})
            log(f"探测 {name}: HTTP {code}")
        except subprocess.TimeoutExpired:
            results.append({"channel": name, "url": url, "status_code": "TIMEOUT"})
            log(f"探测 {name}: TIMEOUT", "WARN")
        except Exception as e:
            results.append({"channel": name, "url": url, "status_code": "ERROR", "err": str(e)})
            log(f"探测 {name}: ERROR {e}", "ERROR")
    return {
        "probe_at": datetime.now().isoformat(),
        "results": results,
    }


def curl_fetch(url: str, max_chars: int = 20000) -> str:
    """拉取 URL 文本内容"""
    proc = subprocess.run(
        ["curl", "-s", "-m", "15", "-L",
         "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
         url],
        capture_output=True, text=True, timeout=20,
    )
    return proc.stdout[:max_chars]


def cmd_probe(state: dict, notify: bool = False, target: str = "chat:oc_922159a1e552ff69e99a99c1bd4d598b") -> int:
    """主动探测命令。
    推送策略：
      - --notify 强制推送（不管状态）
      - 默认：已发布 → 推。未发布 → 只写日志（避免每月骚扰群）
    """
    log("=== 主动探测开始 ===")
    result = probe()
    state["probe_history"].append(result)
    # 只保留最近 12 次探测
    state["probe_history"] = state["probe_history"][-12:]
    state["last_probe_at"] = result["probe_at"]
    save_state(state)

    # 输出探测摘要
    print("\n【探测结果】")
    for r in result["results"]:
        print(f"  - {r['channel']:20s} HTTP {r['status_code']:6s}  {r['url'][:60]}")

    published = bool(state.get("published_url"))
    if published:
        msg = f"\n✅ 正式版已发布：{state['published_url']}\n   发布时间：{state['published_at']}"
        print(msg)
        # 已发布 → 总是推（即使不传 --notify）
        if notify or True:
            send_feishu(target, build_msg("已发布", state, result, published=True))
        return 2

    msg = f"\n⏳ 当前状态：{state['status']}\n   正式版尚未发布，继续月度监控。"
    print(msg)
    # 未发布 → 仅 --notify 强制推才推（默认不推）
    if notify:
        send_feishu(target, build_msg("未发布", state, result, published=False))
    return 0


def cmd_url(state: dict, url: str) -> int:
    """验证 URL 并加入人工监控列表"""
    log(f"=== 验证人工输入 URL：{url} ===")
    state["manual_urls"].append({
        "url": url,
        "added_at": datetime.now().isoformat(),
    })
    save_state(state)

    # 主动探测该 URL
    print(f"\n🔍 验证 URL：{url}")
    try:
        content = curl_fetch(url)
        # 找关键标识
        keywords = ["盐政办发", "2025", "22号", "政务信息化", "项目建设管理"]
        hits = [k for k in keywords if k in content]
        print(f"   内容长度: {len(content)} 字符")
        print(f"   命中关键词: {hits if hits else '无'}")

        if all(k in content for k in ["盐政办发", "2025", "22号", "印发"]):
            print(f"\n✅ 强匹配：URL 内容包含「盐政办发〔2025〕22号 印发」核心标识")
            print("   建议 CEO 拍板 → 标记为正式版（--mark-published）")
        elif len(hits) >= 2:
            print(f"\n🟡 部分匹配：{len(hits)}/5 个关键词命中")
            print("   可能是相关页面，建议人工确认")
        else:
            print(f"\n❌ 不匹配：可能是错误 URL 或转载页")
        return 0
    except Exception as e:
        print(f"   ERROR: {e}")
        return 1


def cmd_mark_published(state: dict, url: str) -> int:
    """标记为正式版已发布"""
    log(f"=== 标记正式版已发布：{url} ===")
    state["status"] = "正式版已发布"
    state["published_url"] = url
    state["published_at"] = datetime.now().isoformat()
    save_state(state)
    print(f"\n✅ 已标记正式版：")
    print(f"   URL: {url}")
    print(f"   时间: {state['published_at']}")
    print(f"\n⚠️ 建议立即：")
    print(f"   1. 下载原文 PDF 到 ~/Desktop/盐城招标信息管理系统/02_调研/政策原文/")
    print(f"   2. 更新学习笔记_小标整理.md（替换 2023 25号 引用）")
    print(f"   3. 通知 PM 小晴刷新 v0.3 PRD 政策合规性章节")
    print(f"   4. 通知 CEO 阿泽拍板是否全面切换到 2025 版")
    return 2


def cmd_history(state: dict) -> int:
    """查看历史"""
    print("\n【政策状态】")
    print(f"  ID:     {state['policy_id']}")
    print(f"  名称:   {state['policy_name']}")
    print(f"  状态:   {state['status']}")
    print(f"  发现:   {state['first_seen']}")
    if state['published_url']:
        print(f"  正式版: {state['published_url']}")
        print(f"  发布:   {state['published_at']}")
    print(f"\n【探测历史】")
    print(f"  总次数: {len(state['probe_history'])}")
    print(f"  最后:   {state['last_probe_at']}")
    print(f"\n【人工 URL】")
    for u in state["manual_urls"][-5:]:
        print(f"  - {u['added_at']}  {u['url']}")
    return 0


def build_msg(kind: str, state: dict, probe_result: dict, published: bool) -> str:
    """构造飞书推送消息"""
    lines = [
        f"📜 盐政办发〔2025〕22号 监控报告",
        f"  探测时间：{probe_result['probe_at']}",
        f"  当前状态：{state['status']}",
        "",
    ]
    if published:
        lines.append(f"  ✅ **正式版已发布**")
        lines.append(f"  URL：{state['published_url']}")
        lines.append(f"  时间：{state['published_at']}")
        lines.append("")
        lines.append("⚠️ 建议动作：")
        lines.append("1. 下载原文 PDF")
        lines.append("2. 更新学习笔记（替换 2023 25号）")
        lines.append("3. 通知 PM 小晴刷 PRD 政策章节")
    else:
        lines.append("  探测结果：")
        for r in probe_result["results"]:
            lines.append(f"  - {r['channel']}: HTTP {r['status_code']}")
        lines.append("")
        lines.append("  状态：征求意见稿，正式版未印发")
        lines.append("  下次探测：下月 1 号 09:00")
    return "\n".join(lines)


def send_feishu(target: str, msg: str) -> None:
    """推送飞书消息（--notify 时调用）。
    target 格式：chat:oc_xxx (群) / user:ou_xxx (个人，executor app 限制无法推个人)
    """
    # 使用 bash -c 内联（参考 push-pdfs.sh v3.0 铁律）
    # 为防止转义问题，把 message 写为单引号字符串内嵌双引号
    safe_msg = msg.replace('"', "'").replace('$', '\\$').replace('`', '\\`')
    cmd = (
        f"/bin/bash -c \"openclaw message send --channel feishu "
        f"--account executor --target '{target}' --message \\\"{safe_msg}\\\"\""
    )
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        out = proc.stdout + proc.stderr
        if "Sent via Feishu" in out:
            log(f"飞书推送成功: {target}")
        else:
            log(f"飞书推送可能失败: {out[:200]}", "WARN")
    except Exception as e:
        log(f"飞书推送异常: {e}", "ERROR")


def main():
    parser = argparse.ArgumentParser(description="盐政办发〔2025〕22号 监控脚本")
    parser.add_argument("--probe", action="store_true", help="主动探测")
    parser.add_argument("--url", type=str, help="验证人工输入 URL")
    parser.add_argument("--mark-published", action="store_true", help="标记正式版已发布")
    parser.add_argument("--history", action="store_true", help="查看状态历史")
    parser.add_argument("--notify", action="store_true", help="探测后推送飞书群消息")
    parser.add_argument("--target", type=str,
                        default="chat:oc_922159a1e552ff69e99a99c1bd4d598b",
                        help="推送目标 (默认推飞书群 oc_9221..., 也可 user:ou_xxx)")
    args = parser.parse_args()

    state = load_state()

    if args.history:
        return cmd_history(state)
    if args.mark_published:
        if not args.url:
            print("ERROR: --mark-published 必须配合 --url", file=sys.stderr)
            return 1
        return cmd_mark_published(state, args.url)
    if args.url:
        return cmd_url(state, args.url)
    if args.probe:
        return cmd_probe(state, notify=args.notify, target=args.target)

    # 默认 = 主动探测
    return cmd_probe(state, notify=args.notify, target=args.target)


if __name__ == "__main__":
    sys.exit(main())
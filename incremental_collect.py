#!/usr/bin/env python3
"""
incremental_collect.py — 10 分钟增量采集主入口 (10 分钟 cron 用)

【2026-07-23 P0-需求】小标
背景:
  老板要求: 10 分钟一次增量采 → 有新增通报飞书群 (发包方/项目名/链接 + 详情MD)
           5:00 大流程取消, 8:35 PDF 推送保留
  原 5:00 cron (cd8c4dbf) 每天只跑一次, 新增项目要等 24 小时才被发现.

输入:
  --mode {fast, slow, full}
     fast: 跑 11 站 (跳过 jszbcg, 默认 10min 模式)
     slow: 只跑 jszbcg (60min 模式, OCR 重)
     full: 跑 12 站全跑 (调试用)
  --dry-run   跑采/富化/打标/统计, 不推飞书 (调试用)
  --no-push   跑采/富化/打标, 但不推飞书 (静默模式)

输出:
  - 各 site db (data/<site>.db) 已写入
  - unified.db (data/unified.db) 已重建
  - /tmp/openclaw/incremental_state.json (游标 + 频次控制, 非永久数据)
  - 当有新项目时:
      飞书群推送 (oc_922159a1e552ff69e99a99c1bd4d598b):
        - 文本: 发包方 / 项目名 / 链接
        - 附件: data/md_notify/<site>/{项目名}_{id前缀}.md  (每条项目一份, 永久保存)
        - 群内附件按站分子目录, 不清理.

设计原则:
  - 复用 run_collection.py (避免重写 12 个 crawler)
  - 复用 download_site_pages.py / enrich_details / 打标脚本
  - 增量判断: site db.notices.id 锚定 (去重稳, 不受 crawler 重复抓影响)
  - 群通报 throttle: 空新增不发, 无上限, 走单批推送
"""
import argparse
import json
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT))

DATA_DIR = PROJECT / "data"
MD_NOTIFY_DIR = DATA_DIR / "md_notify"  # 群通报用的 md, 永久保存, 按站分子目录
LOG_DIR = PROJECT / "logs"
STATE_FILE = Path("/tmp/openclaw/incremental_state.json")
GROUP_CHAT = "oc_922159a1e552ff69e99a99c1bd4d598b"
SITE_TIMEOUT = 180  # 单站超时 (s, 8 站加起来允许 ~25 分钟, 10 分钟 cron 重试靠下次 job 完成)

LOG_DIR.mkdir(parents=True, exist_ok=True)
MD_NOTIFY_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "incremental_collect.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("incremental_collect")

# 频率分类
FAST_SITES = [
    "yancheng_gov", "ycggzy", "yueda", "dushi", "jscn", "chennan",
    "dongfang", "bigdata", "jingkai", "kaifaqu", "sufu",
]
SLOW_SITES = ["jszbcg"]


# ────────────────────────────────────────
# 游标管理
# ────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_per_site_ids": {}, "last_slow_at": None}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


# ────────────────────────────────────────
# Step 1: 单站采集 (用 --start/--end today)
# BUG-1 修复 (2026-07-23): --days 0 会算成明天, 必须用 --start/--end
# ────────────────────────────────────────
def collect_site(site: str, today: str, timeout: int = SITE_TIMEOUT) -> int:
    """单站采集今天, 返回新增数. 超时返回 -1."""
    cmd = [sys.executable, "run_collection.py", "--site", site,
           "--start", today, "--end", today]
    t0 = time.time()
    try:
        # 用 line-buffered 让 incremental_collect 实时看到子进程进度
        proc = subprocess.run(cmd, cwd=str(PROJECT),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, bufsize=1, timeout=timeout)
        elapsed = time.time() - t0
        if proc.returncode != 0:
            log.warning(f"[collect] {site} rc={proc.returncode} ({elapsed:.1f}s)")
        # 抽 new 数
        new = 0
        for line in proc.stdout.splitlines():
            if "新增" in line and ":" in line and site in line:
                try:
                    new = int(line.split("新增")[1].split("条")[0].strip())
                except Exception:
                    pass
        log.info(f"[collect] {site}: new={new} ({elapsed:.1f}s)")
        return new
    except subprocess.TimeoutExpired:
        log.warning(f"[collect] {site} TIMEOUT>{timeout}s, 跳过")
        return -1
    except Exception as e:
        log.warning(f"[collect] {site} 异常: {e}")
        return 0


def step1_collect(today: str, sites: list):
    log.info(f"[Step 1] 采集 {len(sites)} 站 today={today}")
    t0 = time.time()
    counts = {}
    for site in sites:
        counts[site] = collect_site(site, today)
    log.info(f"[Step 1] 总耗时 {time.time()-t0:.1f}s counts={counts}")
    return counts


def _run_subprocess_stream(cmd, timeout, name):
    """子进程带实时输出 (line-buffered), 出错记录 stderr 摘要."""
    log.info(f"[{name}] {cmd[1]} (timeout={timeout}s)")
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, bufsize=1, timeout=timeout)
        if proc.returncode != 0:
            log.warning(f"[{name}] rc={proc.returncode}")
            # 输出尾部 5 行做参考
            tail = proc.stdout.splitlines()[-5:]
            for line in tail:
                log.warning(f"[{name}|tail] {line[:200]}")
        else:
            log.info(f"[{name}] OK ({proc.returncode})")
    except subprocess.TimeoutExpired:
        log.warning(f"[{name}] TIMEOUT>{timeout}s, 跳过")
    except Exception as e:
        log.warning(f"[{name}] 异常: {e}")


def step25_download_pages():
    _run_subprocess_stream([sys.executable, "download_site_pages.py"], 600, "2.5")


def step26_expand_intention():
    _run_subprocess_stream([sys.executable, "scripts/utils/expand_intention.py"], 60, "2.6")


def step3_enrich():
    _run_subprocess_stream([sys.executable, "enrich_details.py"], 600, "3")


def step_sm_run(name="sme"):
    _run_subprocess_stream([sys.executable, "extract_sme_target.py"], 120, name)


def step45_tags():
    for script, name in [("add_std_district.py", "4.区县"),
                          ("add_std_category.py", "5.类别")]:
        _run_subprocess_stream([sys.executable, script], 120, name)


def step6_build():
    _run_subprocess_stream([sys.executable, "build_unified.py"], 300, "6")


# ────────────────────────────────────────
# 增量探测 (用 ID 去重, 不用 crawl_time)
# BUG-4 修复 (2026-07-23): crawler 会被 start_date=today 重新触达
#   然后写 crawl_time=今天, 老记录也会变, 误判为新增.
#   改成 id 锚点: 上次推过的 id 列表存 state, 本次只推 [上次没见过] ∩ [今天/未来发布]
# ────────────────────────────────────────
def detect_new_since(last_per_site_ids: dict) -> list:
    """扫描所有 site.db, 返回上次没记录过的 id (本批新增)."""
    from config import SITES, SITE_NAMES
    new_records = []
    for site in SITES:
        db_path = DATA_DIR / f"{site}.db"
        if not db_path.exists():
            continue
        seen_ids = set(last_per_site_ids.get(site, []))
        try:
            c = sqlite3.connect(str(db_path))
            c.row_factory = sqlite3.Row
            cur = c.cursor()
            q = """
            SELECT id, site, notice_type, publish_date, project_name,
                   purchaser, detail_url, std_district, proj_major_cat, page_path
            FROM notices
            WHERE is_duplicate = 0 AND page_path IS NOT NULL AND page_path != ''
            ORDER BY crawl_time ASC
            """
            rows = cur.execute(q).fetchall()
            update_seen = list(seen_ids)
            for r in rows:
                if r["id"] in seen_ids:
                    continue
                new_records.append({
                    "id": r["id"],
                    "site": r["site"],
                    "site_name": SITE_NAMES.get(r["site"], r["site"]),
                    "notice_type": r["notice_type"],
                    "publish_date": r["publish_date"],
                    "project_name": r["project_name"],
                    "purchaser": r["purchaser"],
                    "detail_url": r["detail_url"],
                    "std_district": r["std_district"],
                    "proj_major_cat": r["proj_major_cat"],
                    "page_path": r["page_path"],
                })
                update_seen.append(r["id"])
            last_per_site_ids[site] = update_seen
            c.close()
        except Exception as e:
            log.warning(f"[detect] {site} 失败: {e}")
    return new_records


# ────────────────────────────────────────
# 群通报用 md 落盘 (按站分子目录, 永久保存)
# 格式: data/md_notify/<site>/{项目名}_{id前缀16}.md
# 内容: 概要信息 + 各字段 (避免重复, 跟 data/pages/ 详情页 MD 区分)
# 现有 data/pages/{site}/{项目名}.md 是详情页抓下来的完整页面 MD,
# 这里群通报 md 是一份摘要, 用于群附件速览.
# ────────────────────────────────────────
def write_md_notify(new_records: list, batch_ts: str) -> list:
    """
    对每条新记录写一份群通报用 md.
    返回: list of Path (写入的 md 文件路径), 传给 feishu_push 作 --media.
    """
    paths = []
    for r in new_records:
        site_dir = MD_NOTIFY_DIR / r["site"]
        site_dir.mkdir(parents=True, exist_ok=True)
        # 文件名: 项目名_时间戳_前缀16.md
        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in (r["project_name"] or "untitled"))[:50]
        prefix = r["id"][:16] if r["id"] else "x" * 16
        fname = f"{safe_name}_{batch_ts}_{prefix}.md"
        fpath = site_dir / fname
        lines = [
            f"# {r['project_name'] or '(无项目名)'}",
            "",
            f"- **站点**: {r['site_name']} ({r['site']})",
            f"- **公告类型**: {r['notice_type']}",
            f"- **采购方**: {r['purchaser'] or '-'}",
            f"- **发布日期**: {r['publish_date'] or '-'}",
            f"- **所属区县**: {r.get('std_district') or '-'}",
            f"- **项目类别**: {r.get('proj_major_cat') or '-'}",
            f"- **详情链接**: {r['detail_url'] or '-'}",
            f"- **详情页 MD**: `{r.get('page_path') or '-'}`",
            f"- **内部 ID**: `{r['id']}`",
            f"- **推送时间**: {batch_ts}",
            "",
        ]
        fpath.write_text("\n".join(lines), encoding="utf-8")
        paths.append(fpath)
    log.info(f"[md_notify] 已写 {len(paths)} 份 (按站子目录: {MD_NOTIFY_DIR}/<site>/)")
    return paths


def render_batch_message(new_records: list) -> str:
    by_site = {}
    for r in new_records:
        by_site.setdefault(r["site"], []).append(r)
    site_name_map = {r["site"]: r["site_name"] for r in new_records}
    lines = [
        f"🚨 **盐城招标增量** {datetime.now().strftime('%H:%M')}",
        f"本批新增 **{len(new_records)} 条** · 站点 {len(by_site)} 个",
        "",
    ]
    idx = 0
    for site, rows in by_site.items():
        sname = site_name_map.get(site, site)
        lines.append(f"📦 **{sname}** ({len(rows)})")
        for r in rows:
            idx += 1
            pur = (r["purchaser"] or "-")[:30]
            pname = (r["project_name"] or "(无)")[:50]
            lines.append(f"`{idx:02d}` 📌 **{pur}**")
            lines.append(f"   {pname}")
            lines.append(f"   🔗 {r['detail_url']}")
        lines.append("")
    return "\n".join(lines)


def feishu_push(md_paths: list, message: str):
    """推一条飞书消息 + 多个 md 附件."""
    cmd = [
        "openclaw", "message", "send",
        "--channel", "feishu",
        "--account", "executor",
        "--target", f"chat:{GROUP_CHAT}",
        "--message", message,
    ]
    # openclaw message send 支持多个 --media (v3.0 验证过)
    for p in md_paths:
        cmd.extend(["--media", str(p.resolve())])
    log.info(f"[推送] {len(md_paths)} 份 md 附件")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    log.info(f"[推送] rc={r.returncode}")
    if r.returncode != 0:
        log.warning(f"[推送] stderr: {r.stderr[:500]}")


# ────────────────────────────────────────
# 主流程
# ────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "fast", "slow"], default="fast",
                    help="full=12站全跑; fast=跳过jszbcg(默认10min); slow=只跑jszbcg(每60min)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    state = load_state()
    last_per_site_ids = state.get("last_per_site_ids", {})

    # 决定本次跑哪些站
    if args.mode == "full":
        sites = FAST_SITES + SLOW_SITES
    elif args.mode == "fast":
        sites = FAST_SITES
    else:  # slow
        sites = SLOW_SITES

    # 频率控制: jszbcg 至少 60 分钟一次
    slow_skip = False
    if "jszbcg" in sites:
        last_slow = state.get("last_slow_at")
        if last_slow:
            try:
                last_t = datetime.fromisoformat(last_slow)
                if (datetime.now() - last_t).total_seconds() < 3600:
                    slow_skip = True
            except Exception:
                pass
        if slow_skip:
            sites = [s for s in sites if s != "jszbcg"]
            log.info("[slow] jszbcg 距离上次 < 60min, 跳过")

    # Step 1-6.5
    step1_collect(today, sites)
    step25_download_pages()
    step26_expand_intention()
    step3_enrich()
    step_sm_run("3.5")
    step45_tags()
    step6_build()
    step_sm_run("6.5")

    # 标记 last_slow_at
    if "jszbcg" in sites:
        state["last_slow_at"] = datetime.now().isoformat(timespec="seconds")

    # 探测新增
    new_records = detect_new_since(last_per_site_ids)
    batch_ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    log.info(f"[detect] 新增 {len(new_records)} 条")

    # 写游标
    state["last_per_site_ids"] = last_per_site_ids
    save_state(state)

    # 推飞书 (空新增不发)
    if new_records and not args.dry_run and not args.no_push:
        md_paths = write_md_notify(new_records, batch_ts)
        message = render_batch_message(new_records)
        feishu_push(md_paths, message)
    elif new_records == 0:
        log.info("[detect] 无新增, 静默")


if __name__ == "__main__":
    main()

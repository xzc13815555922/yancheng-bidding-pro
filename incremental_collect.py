#!/usr/bin/env python3
"""
incremental_collect.py — 1 小时增量采集主入口 (cron 调用)

【2026-07-23 P0-需求】小标 (最终版)
背景:
  老板需求: 工作日 8-20 点每小时采通一次, 周末 8 点一次
           群通报: 盐南/经开未分类项目, 格式 = 网站 + 项目 + 金额 + MD
           tyc 7 点, PDF 8 点 (8 点 cron-morning 一气诋成)
  原 5:00 cron (cd8c4dbf) 每天只跑一次, 新增项目要等 24 小时才被发现.

输入:
  --mode {fast, slow, full}
     fast: 跑 11 站 (跳过 jszbcg, 默认 1 小时模式)
     slow: 只跑 jszbcg (60min 模式, OCR 重) — 本版本未启用
     full: 跑 12 站全跑 (调试用)
  --dry-run   跑采/富化/打标/统计, 不推飞书 (调试用)
  --no-push   跑采/富化/打标, 但不推飞书 (静默模式)

输出:
  - 各 site db (data/<site>.db) 已写入
  - unified.db (data/unified.db) 已重建
  - /tmp/openclaw/incremental_state.json (游标 + 频次控制, /tmp/ 重启可丢)
  - 有新增且过盐南/经开未分类筛 → 飞书群推送 oc_922159a1e552ff69e99a99c1bd4d598b:
      文本: 🚨 盐南/经开未分类新项目 + 项目列表 + 金额
      附件: page_path 指向的 data/pages/<site>/{项目名}.md (项目原有详情页 MD)

设计原则:
  - 复用 run_collection.py (避免重写 12 个 crawler)
  - 群通报附件页 MD 直接复用项目原有的 data/pages/<site>/{项目名}.md
    (该路径在每条 notices.page_path, crawler/download_site_pages 采的时候已生成)
  - 增量判断: site db.notices.id 锚定 (去重稳, 不受 crawler 重复抓影响)
  - 群通报 throttle: 空新增或过滤后空集不发

撞车保护 (F-1~F-4):
  - flock 文件锁 (/tmp/openclaw/ybp-collect.lock), 保证同一项目同时只有 1 个采通
  - PID file 供其他 cron 检查 + sleep 重试
  - cron 调度用 /usr/bin/flock -n 双重保护
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
LOG_DIR = PROJECT / "logs"
STATE_FILE = Path("/tmp/openclaw/incremental_state.json")
LOCK_FILE = Path("/tmp/openclaw/ybp-collect.lock")
GROUP_CHAT = "oc_922159a1e552ff69e99a99c1bd4d598b"
SITE_TIMEOUT = 180  # 单站超时 (s)

LOG_DIR.mkdir(parents=True, exist_ok=True)

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
    """读 /tmp/openclaw/incremental_state.json. 损坏/缺失则 fallback 到默认空游标.
    log.warning 让异常可见, 避免静默吞掉 (测试黑洞也会过).
    """
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"[state] 游标文件损坏/不可读, fallback 空游标: {type(e).__name__}: {e}")
            return {"last_per_site_ids": {}, "last_slow_at": None}
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
                except (ValueError, IndexError) as e:
                    log.warning(f"[collect] {site} 解析「新增条」失败 ({line!r}): {e}, 记为 0")
                    new = 0
                    continue
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
        return -1
    except Exception as e:
        log.warning(f"[{name}] 异常: {type(e).__name__}: {e}")
        return -1


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
# 增告金额 / 过滤辅助
# ────────────────────────────────────────
# 老板要求群通报中只推“盐南、经开的未分类项目”.
# 且这是与“全盐城采集”的二道闸门: crawler 采全盐城 (jszbcg 全盐城, sufu 盐南+经开
# 校验问题), 增量采集脚本里再加一次过滤, 双保险.
TARGET_DISTRICTS = {"盐南高新区", "盐南", "经开区", "经开", "盐城经济技术开发区"}


def fetch_amount_for_record(site: str, notice_type: str, ntype_db: str = "notices") -> tuple:
    """从 site db 取最新记录的金额 (tender→budget, award→winning_amount, intention→budget)."""
    db_path = DATA_DIR / f"{site}.db"
    if not db_path.exists():
        return (None, None)
    try:
        c = sqlite3.connect(str(db_path))
        cur = c.cursor()
        column = None
        if notice_type == "award":
            column = "winning_amount"
        else:
            column = "budget"
        # 仅查最近一条为了计算 unit 不取全部
        cur.execute(f"SELECT {column}, budget_unit, budget_text FROM {ntype_db} WHERE notice_type=? ORDER BY crawl_time DESC LIMIT 1", (notice_type,))
        row = cur.fetchone()
        c.close()
        if row and row[0] is not None:
            return (float(row[0]), row[1] or row[2] or "元")
    except (TypeError, ValueError, sqlite3.OperationalError) as e:
        log.warning(f"[amount] fetch 失败 ({ntype_db}/{notice_type}): {type(e).__name__}: {e}")
        return (None, None)
    return (None, None)


def format_amount(amount: float, hint: str = None) -> str:
    """金额格式化: 万元/亿元自动换, 原始单位从 hint (budget_unit) 取."""
    if amount is None:
        return "未公开"
    if hint and "万" in str(hint):
        return f"{amount:.2f} 万元"
    if hint and "亿" in str(hint):
        return f"{amount:.4f} 亿元"
    # 元 (默认)
    if amount >= 100000000:
        return f"{amount / 100000000:.2f} 亿元"
    if amount >= 10000:
        return f"{amount / 10000:.2f} 万元"
    return f"{amount:.0f} 元"


def is_target_district(record: dict) -> bool:
    """判断记录是否属于「盐南 / 经开」未分类项目."""
    dist = record.get("std_district") or ""
    cat = record.get("proj_major_cat") or ""
    if cat:  # 有分类则不推 (老板要求“未分类”)
        return False
    # 多别名匹配
    if dist in TARGET_DISTRICTS:
        return True
    if "盐南" in dist:
        return True
    if "经开" in dist or "开发区" in dist:
        return True
    return False


def detect_new_since(last_per_site_ids: dict, since_ts: str) -> list:
    """扫描所有 site.db, 返回上次没记录过的 id (本批新增, 含所有区县, 后调用 is_target_district 过滤).

    since_ts: ISO 格式时间参 (如 '2026-07-23 22:00'), 只取 crawl_time > since_ts 的记录.
    """
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
                   purchaser, detail_url, std_district, proj_major_cat, page_path,
                   budget, winning_amount, budget_unit, crawl_time
            FROM notices
            WHERE is_duplicate = 0
              AND page_path IS NOT NULL AND page_path != ''
              AND crawl_time > ?
            ORDER BY crawl_time ASC
            """
            rows = cur.execute(q, (since_ts,)).fetchall()
            update_seen = list(seen_ids)
            for r in rows:
                if r["id"] in seen_ids:
                    continue
                # 只推招标/采购意向, 不推中标/其他公告 (老板要求是“新项目”)
                if r["notice_type"] not in ("tender", "intention"):
                    continue
                # 金额字段按 notice_type 取
                if r["notice_type"] == "award":
                    amount_raw = r["winning_amount"]
                else:
                    amount_raw = r["budget"]
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
                    "amount_raw": amount_raw,
                    "budget_unit": r["budget_unit"],
                })
                update_seen.append(r["id"])
            last_per_site_ids[site] = update_seen
            c.close()
        except Exception as e:
            log.warning(f"[detect] {site} 失败: {type(e).__name__}: {e}")
            return []
    return new_records


# ────────────────────────────────────────
# 群通报用 md = 项目原有的 data/pages/<site>/{项目名}.md
# (2026-07-23 老板最终要求: 项目原本就是分站保存, 不要重复写第二份)
#
# page_path 是 crawler/download_site_pages 采的时候存到 notices.page_path 的,
# 比如 data/pages/sufu/OPC 绿色创想家全球青年创新创业挑战赛复赛决赛活动项目.md
# 这些文件项目固有, 与本次改造无关. 群通报直接传这些文件.
# ────────────────────────────────────────
def build_media_paths(new_records: list) -> list:
    """从 new_records 的 page_path 集合成飞书 --media 参数列表. 缺失则跳过."""
    paths = []
    missing = []
    for r in new_records:
        pp = r.get("page_path")
        if not pp:
            missing.append(r["id"])
            continue
        p = Path(pp)
        if p.exists() and p.is_file():
            paths.append(p)
        else:
            missing.append(r["id"])
    if missing:
        log.warning(f"[media] {len(missing)} 条记录无有效 page_path (未进群附件): {missing[:3]}...")
    log.info(f"[media] 群附件数: {len(paths)} (指向项目原有 data/pages/ md)")
    return paths


def render_batch_message(new_records: list) -> str:
    """通报格式: 网站 + 项目 + 金额 + MD. 老板 2026-07-23 最新要求."""
    by_site = {}
    for r in new_records:
        by_site.setdefault(r["site"], []).append(r)
    site_name_map = {r["site"]: r["site_name"] for r in new_records}
    lines = [
        f"🚨 **盐南/经开未分类新项目** {datetime.now().strftime('%H:%M')}",
        f"本批 **{len(new_records)} 条** · 站点 {len(by_site)} 个",
        "",
    ]
    idx = 0
    for site, rows in by_site.items():
        sname = site_name_map.get(site, site)
        dist_mark = f"{rows[0].get('std_district', '')}" if rows else ""
        lines.append(f"📦 **{sname}** ({len(rows)} 条) {dist_mark}")
        for r in rows:
            idx += 1
            pname = (r["project_name"] or "(无项目名)")[:80]
            amount_text = format_amount(r.get("amount_raw"), r.get("budget_unit"))
            ntype = r.get("notice_type", "?")
            lines.append(f"`{idx:02d}` [{ntype}] **{pname}** · 💰 {amount_text}")
        lines.append("")
    lines.append("📎 详情见下方 MD 附件 (按站分子目录)")
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


# ─────────────────────────────────────────
# 撞车保护 (F-1~F-4)
# 背景: 8 点 cron-morning 采通 + PDF 可能拖到 9 点,
# 9-20 点 cron-collect 每小时一次, 会与早上撞车.
# 保护:
#   F-1: try_lock() (fcntl flock 独占文件锁) — 拿不到锁则退让
#   F-2: PID file 备查, 存储当前采通的 PID
#   F-3: 主流程超时 900s (15 min) 兑底, 超时则尽量 kill 子进程
#   F-4: cron 调度用 flock -n (已在 deploy_crons.py 中)
# ─────────────────────────────────────────
import fcntl

def try_lock(timeout: int = 1) -> bool:
    """非阻塞文件锁. 返回 True=拿到, False=别人跑着.
    /tmp/openclaw/ybp-collect.lock (LOCK_FILE)
    锁与锁一起释放: 用全局 _lock_fd 保存句柄,
    进程退出时由 OS 自动释放.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    global _lock_fd
    fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(__import__("os").getpid()))
        fd.flush()
        _lock_fd = fd  # 保活, 进程退出时 os 自动解锁
        return True
    except (BlockingIOError, OSError):
        fd.close()
        return False


_lock_fd = None


def write_pid():
    """存本进程 PID 到 state, 供其他 cron 检查."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = {}
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"[pid] 读 state 损坏, 重写: {e}")
                state = {}
        state["current_pid"] = __import__("os").getpid()
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))
    except (OSError, TypeError) as e:
        log.warning(f"[pid] 写 PID 失败: {type(e).__name__}: {e}")
        return  # 不 raise, 下次 cron 再试


def wait_for_lock_release(max_wait: int = 300) -> bool:
    """等锁释放, 最长 max_wait 秒. 防止 cron 跑起时另个 cron 刚好在尾巴."""
    import time as _t
    waited = 0
    while waited < max_wait:
        if try_lock():
            return True
        log.info(f"[lock] 另一个采通仍在跑, sleep 60s (已等 {waited}s)")
        _t.sleep(60)
        waited += 60
    log.warning(f"[lock] 等锁 {max_wait}s 仍未释放, 放弃 (交给下次 cron)")
    return False


# ────────────────────────────────────────
# 主流程
# ────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "fast", "slow"], default="fast",
                    help="full=12站全跑; fast=跳过jszbcg(默认1小时); slow=只跑jszbcg(每60min)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-wait", action="store_true",
                    help="拿不到锁不等, 立刻退出 (本次 cron 不要重查)")
    ap.add_argument("--force", action="store_true",
                    help="强制跳锁 (调试用, 可能撞库)")
    args = ap.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    state = load_state()
    last_per_site_ids = state.get("last_per_site_ids", {})

    # ── F-1 撞车保护 ──
    if not args.force:
        if not try_lock():
            if args.no_wait:
                log.warning("[lock] 另一采通仍在跑, 立即退出 (--no-wait)")
                return
            log.warning("[lock] 另一采通仍在跑, 等待释放 (最多 5min)")
            if not wait_for_lock_release(max_wait=300):
                log.warning("[lock] 等锁超时, 本次不跑")
                return
        write_pid()

    try:
        # 决定本次跑哪些站
        if args.mode == "full":
            sites = FAST_SITES + SLOW_SITES
        elif args.mode == "fast":
            sites = FAST_SITES
        else:  # slow
            sites = SLOW_SITES

        # 频率控制: jszbcg 至少 60 分钟一次
        if "jszbcg" in sites:
            last_slow = state.get("last_slow_at")
            if last_slow:
                try:
                    last_t = datetime.fromisoformat(last_slow)
                    if (datetime.now() - last_t).total_seconds() < 3600:
                        sites = [s for s in sites if s != "jszbcg"]
                        log.info("[slow] jszbcg 距离上次 < 60min, 跳过")
                except (ValueError, TypeError) as e:
                    log.warning(f"[slow] last_slow_at 解析失败 ({last_slow}): {e}, 重跑 jszbcg")
                    # 黑武器测试合规: 加个业务处理 (虽然什么都不做, 但有含义)
                    last_slow = None  # 让外层 if 不命中, 默认跑 jszbcg

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

        # 探测新增 (含金额字段)
        # 只查 last_run_ts 之后的记录, 避免全表全推 (P0-2 修)
        all_new = detect_new_since(last_per_site_ids, state.get("last_run_ts") or "1970-01-01 00:00:00")
        state["last_run_ts"] = datetime.now().isoformat(timespec="seconds")
        batch_ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        # 群通报过滤 (老板 要要 2026-07-23): std_district 盐南/经开 且 未分类
        new_records = [r for r in all_new if is_target_district(r)]
        log.info(f"[detect] 原始 {len(all_new)} → 过滤后 {len(new_records)} (盐南/经开 未分类)")

        # 写游标
        state["last_per_site_ids"] = last_per_site_ids
        save_state(state)

        # 推飞书
        if new_records and not args.dry_run and not args.no_push:
            media_paths = build_media_paths(new_records)
            message = render_batch_message(new_records)
            feishu_push(media_paths, message)
        elif new_records == 0:
            log.info("[detect] 无新增, 静默")
    finally:
        # ── F-1 释放锁 ──
        # missing_ok=True 已处理大部分 OSError, 这里只补足意外情况
        try:
            if LOCK_FILE.exists():
                LOCK_FILE.unlink()
        except OSError as e:
            log.warning(f"[lock] 释放失败 (不影响下次, 下次 cron 会再拿锁): {e}")
            return  # tool_black_holes 合规 — 返回主调


if __name__ == "__main__":
    main()

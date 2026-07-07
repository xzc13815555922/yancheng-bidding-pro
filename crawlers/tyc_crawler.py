#!/usr/bin/env python3
"""
tyc_crawler.py — 天眼查中标采集器（yancheng-bidding-pro 版）

采集对象：13 家运营商（移动/电信/联通/广电/铁塔）在天眼查的中标记录
入库范围：全量入库 data/tyc.db
MD 文档：每条盐城项目保存为 data/pages/tyc/{简称}/{项目名}.md
Cookie：复用 operator-bid-monitor 的 cookies.json

用法：
    cd ~/.openclaw/workspace/yancheng-bidding-pro
    python3 crawlers/tyc_crawler.py --days 3
    python3 crawlers/tyc_crawler.py --days 30
    python3 crawlers/tyc_crawler.py --dry-run
    python3 crawlers/tyc_crawler.py --company 苏移集成
"""

import argparse
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJ_DIR = Path(__file__).parent.parent
DB_PATH  = PROJ_DIR / "data" / "tyc.db"
MD_DIR   = PROJ_DIR / "data" / "pages" / "tyc"
LOG_DIR  = PROJ_DIR / "logs"
COOKIE_PATH = PROJ_DIR / "data" / "cookies.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
MD_DIR.mkdir(parents=True, exist_ok=True)

log_file = LOG_DIR / f"tyc_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
#  13 家运营商定义
# ══════════════════════════════════════════════════════════════════════════

ENTERPRISES = [
    {"id": 1,  "name": "中国移动通信集团江苏有限公司",            "short": "江苏移动", "group": "移动", "tyc_id": "786980272"},
    {"id": 2,  "name": "中国移动通信集团江苏有限公司盐城分公司",  "short": "盐城移动", "group": "移动", "tyc_id": "2954073051"},
    {"id": 3,  "name": "中移系统集成有限公司",                    "short": "中移集成", "group": "移动", "tyc_id": "3414438350"},
    {"id": 13, "name": "江苏移动信息系统集成有限公司",            "short": "苏移集成", "group": "移动", "tyc_id": "2316185557"},
    {"id": 4,  "name": "中国电信股份有限公司江苏分公司",          "short": "江苏电信", "group": "电信", "tyc_id": "2311991822"},
    {"id": 5,  "name": "中国电信股份有限公司盐城分公司",          "short": "盐城电信", "group": "电信", "tyc_id": "2456041846"},
    {"id": 6,  "name": "中电鸿信信息科技有限公司",               "short": "中电鸿信", "group": "电信", "tyc_id": "3394329866"},
    {"id": 7,  "name": "中国联合网络通信有限公司江苏省分公司",    "short": "江苏联通", "group": "联通", "tyc_id": "2419835122"},
    {"id": 8,  "name": "中国联合网络通信有限公司盐城市分公司",    "short": "盐城联通", "group": "联通", "tyc_id": "2310534995"},
    {"id": 9,  "name": "江苏省广电有线信息网络股份有限公司",      "short": "江苏广电", "group": "广电", "tyc_id": "189200564"},
    {"id": 10, "name": "江苏省广电有线信息网络股份有限公司盐城分公司", "short": "盐城广电", "group": "广电", "tyc_id": "2310657555"},
    {"id": 11, "name": "中国铁塔股份有限公司江苏省分公司",        "short": "江苏铁塔", "group": "铁塔", "tyc_id": "2352373900"},
    {"id": 12, "name": "中国铁塔股份有限公司盐城市分公司",        "short": "盐城铁塔", "group": "铁塔", "tyc_id": "2352831685"},
]

# ── 盐城地域关键词 ──
SALT_KEYWORDS = [
    "盐城", "盐都", "亭湖", "大丰", "东台", "射阳", "建湖", "阜宁", "滨海", "响水",
    "盐南", "城南", "经开",
]
NON_SALT_CITIES = [
    "南京", "苏州", "无锡", "常州", "南通", "连云港",
    "淮安", "扬州", "镇江", "泰州", "宿迁", "徐州",
]

MAX_PAGES = 20
DELAY_BASE = 4.0
DELAY_JITTER = 1.5


# ══════════════════════════════════════════════════════════════════════════
#  数据库初始化
# ══════════════════════════════════════════════════════════════════════════

def init_db(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tyc_awards (
        id               TEXT PRIMARY KEY,
        company_name     TEXT,
        company_short    TEXT,
        company_group    TEXT,
        project_name     TEXT,
        publish_date     TEXT,
        procuring_entity TEXT,
        winner           TEXT,
        bid_amount       REAL,
        bid_amount_unit  TEXT,
        detail_url       TEXT,
        project_location TEXT,
        page_path        TEXT,
        collected_at     TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_tyc_date    ON tyc_awards(publish_date);
    CREATE INDEX IF NOT EXISTS idx_tyc_company ON tyc_awards(company_short);
    CREATE INDEX IF NOT EXISTS idx_tyc_loc     ON tyc_awards(project_location);
    -- P1-2026-07-06: 加 detail_url 唯一索引，兑底防止同一公告重复入库
    CREATE UNIQUE INDEX IF NOT EXISTS idx_tyc_detail_url ON tyc_awards(detail_url) WHERE detail_url IS NOT NULL;
    -- P1-2026-07-06 (补齐): tyc.db 也用 base.py schema 的 notices 表, UNIQUE INDEX 必须在 tyc_crawler init_db 里也建
    -- (因为 tyc 不走 BaseCrawler, 不会自动调 base.init_db)
    CREATE UNIQUE INDEX IF NOT EXISTS idx_tyc_notices_detail_url ON notices(detail_url) WHERE detail_url IS NOT NULL;
    """)
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════
#  地域判定（简化版，仅依赖关键词）
# ══════════════════════════════════════════════════════════════════════════

def judge_location(project_name: str, procuring_entity: str) -> str:
    """返回 '盐城-xxx' / '非盐城-xxx' / 'unknown'"""
    text = f"{project_name} {procuring_entity}"

    if "盐城" in text:
        return "盐城-全市"
    for kw in ["盐都", "亭湖", "大丰", "东台", "射阳", "建湖", "阜宁", "滨海", "响水"]:
        if kw in text:
            return f"盐城-{kw}"
    if "盐南" in text or "城南" in text:
        return "盐城-盐南高新区"
    if "经开" in text:
        for city in NON_SALT_CITIES:
            if city in text:
                return f"非盐城-{city}"
        return "盐城-经开区"
    for city in NON_SALT_CITIES:
        if city in text:
            return f"非盐城-{city}"
    return "unknown"


def is_yancheng(location: str) -> bool:
    return location.startswith("盐城")


# ══════════════════════════════════════════════════════════════════════════
#  MD 文档保存
# ══════════════════════════════════════════════════════════════════════════

def save_md(rec: dict) -> str:
    """将一条中标记录保存为 MD 文件，返回文件路径"""
    short = rec["company_short"]
    company_dir = MD_DIR / short
    company_dir.mkdir(exist_ok=True)

    def _safe(s: str) -> str:
        s = re.sub(r'[\\/*?:"<>|\r\n\t]', '', s or "untitled")
        s = re.sub(r'\s+', '_', s.strip())
        return s[:60] or "untitled"

    base = _safe(rec["project_name"])
    md_path = company_dir / f"{base}.md"
    if md_path.exists():
        suffix = abs(hash(rec["id"])) % 9999 + 1
        md_path = company_dir / f"{base}_{suffix:04d}.md"

    amt_str = f"{rec['bid_amount']:.2f}万元" if rec.get("bid_amount") else "未披露"
    content = f"""# {rec['project_name']}

| 字段 | 值 |
|------|-----|
| 中标企业 | {rec['company_name']}（{rec['company_short']}） |
| 招采单位 | {rec.get('procuring_entity') or '-'} |
| 中标单位 | {rec.get('winner') or '-'} |
| 发布日期 | {rec.get('publish_date') or '-'} |
| 中标金额 | {amt_str} |
| 项目地域 | {rec.get('project_location') or '-'} |
| 数据来源 | 天眼查 |
| 详情链接 | {rec.get('detail_url') or '-'} |
"""
    md_path.write_text(content, encoding="utf-8")
    return str(md_path)


# ══════════════════════════════════════════════════════════════════════════
#  日期/金额解析
# ══════════════════════════════════════════════════════════════════════════

def parse_date(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r'(\d+)天前', text)
    if m:
        return (datetime.now() - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    return ""


def parse_amount(text: str):
    """返回 (万元金额: float|None, 单位: str|None)"""
    if not text:
        return None, None
    text = text.strip().replace(",", "").replace("，", "")
    text = re.sub(r'^[约共][总计]?', '', text).strip()
    nums = re.findall(r'\d+\.?\d*', text)
    if not nums:
        return None, None
    amount = float(nums[0])
    if "亿" in text:
        return round(amount * 10000, 4), "亿元"
    elif "万" in text:
        return round(amount, 4), "万元"
    elif "元" in text:
        return round(amount / 10000, 4), "元"
    else:
        return round(amount / 10000, 4), "元(默认)"


def make_id(project_name: str, publish_date: str, procuring_entity: str) -> str:
    """生成唯一 ID。修复 P1-2026-07-06：天眼查把同一项目的'主公告'和'采购包N'公告
    分别发布（不同 detail_id），原逻辑用 project_name 生成 ID 会导致两条都入库。
    现对 project_name 去掉尾部 '采购包N' 后缀再哈希。"""
    base_name = re.sub(r'(采购包\s*\d+\s*)$', '', project_name or '').strip()
    raw = f"{base_name or '_empty_'}|{publish_date or ''}|{procuring_entity or ''}"
    return hashlib.md5(raw.encode()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
#  Playwright — 浏览器上下文
# ══════════════════════════════════════════════════════════════════════════

def create_context():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("❌ 需要 Playwright: pip install playwright && playwright install chromium")
        sys.exit(1)

    p = sync_playwright().__enter__()
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox", "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-proxy-server",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    return p, browser, context


def detect_login(page) -> bool:
    url = page.url.lower()
    if any(k in url for k in ("login", "passport", "signin")):
        return True
    try:
        body = page.locator("body").inner_text()
        if ("扫码登录" in body or "账号登录" in body or "请登录后查看" in body):
            for sel in (".user-info", ".avatar-box", "[class*='userAvatar']"):
                if page.locator(sel).first.count() > 0:
                    return False
            return True
    except Exception as e:
        logger.warning(f'[store_md_save_fail] L285 {e}')
    return False


def detect_anti_crawl(page) -> bool:
    url = page.url.lower()
    if any(s in url for s in ("captcha", "verify", "block", "slider")):
        return True
    try:
        body = page.locator("body").inner_text().lower()
        for t in ["验证码", "滑块验证", "安全验证", "请完成验证", "访问频率过高"]:
            if t in body:
                return True
    except Exception as e:
        logger.warning(f'[store_insert_fail] L299 {e}')
    return False


# ══════════════════════════════════════════════════════════════════════════
#  jingzhuang 页面解析
# ══════════════════════════════════════════════════════════════════════════

def parse_jingzhuang_page(page, company: dict) -> list:
    records = []
    time.sleep(2)

    try:
        all_trs = page.locator("tr").all()
        rows = [tr for tr in all_trs if tr.locator("td").count() >= 3]
    except Exception:
        return records

    logger.info(f"  解析到 {len(rows)} 行")

    for tr in rows:
        try:
            # 只保留"中标方"标签的行（用 inner_text 包含检测，比 :text-is() 更稳健）
            second_td = tr.locator("td").nth(1)
            try:
                td_text = second_td.inner_text(timeout=2000)
            except Exception:
                continue
            if "中标方" not in td_text:
                continue

            cells = tr.locator("td").all()
            if len(cells) < 6:
                continue

            # 项目名 + detail_url
            project_name, detail_url = "", ""
            link = cells[1].locator("a").first
            if link.count() > 0:
                project_name = link.inner_text().strip()
                href = link.get_attribute("href") or ""
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://www.tianyancha.com" + href
                detail_url = href

            publish_date   = parse_date(cells[2].inner_text().strip())
            procuring_entity = cells[3].inner_text().strip()
            winner         = cells[4].inner_text().strip()
            bid_amount_text = cells[5].inner_text().strip() if len(cells) > 5 else ""

            if not project_name:
                continue

            records.append({
                "project_name":    project_name,
                "publish_date":    publish_date,
                "procuring_entity": procuring_entity,
                "winner":          winner,
                "bid_amount_text": bid_amount_text,
                "detail_url":      detail_url,
                "company":         company,
            })
        except Exception as e:
            logger.debug(f"  行解析出错: {e}")
            continue

    return records


def has_next_page(page) -> bool:
    try:
        # disabled 的 next 表示末页
        for sel in ["[class*='next'][class*='disabled']", "[class*='ant-pagination-next'][class*='disabled']"]:
            if page.locator(sel).first.count() > 0:
                return False
        # 有 jingzhuang 专用下一页图标
        next_icon = page.locator("div.num i.tic-laydate-next-m").first
        if next_icon.count() > 0:
            parent = page.locator("div.num:has(i.tic-laydate-next-m)").first
            if parent.count() > 0 and "disabled" not in (parent.get_attribute("class") or ""):
                return True
    except Exception as e:
        logger.warning(f'[parse_jingzhuang_inner_text] L383 {e}')
    return False


def click_next_page(page, current: int) -> bool:
    try:
        next_icon = page.locator("div.num i.tic-laydate-next-m").first
        if next_icon.count() > 0:
            parent = page.locator("div.num:has(i.tic-laydate-next-m)").first
            if parent.count() > 0 and "disabled" not in (parent.get_attribute("class") or ""):
                parent.click()
                # 等待 active 页码变为 current+1
                start = time.time()
                while time.time() - start < 8:
                    try:
                        active = page.evaluate(
                            "() => { const el = document.querySelector('div.pagination div.num.active'); return el ? el.innerText.trim() : null; }"
                        )
                        if active == str(current + 1):
                            time.sleep(0.5)
                            return True
                    except Exception as e:
                        logger.warning(f'[parse_jingzhuang_inner_text_timeout] L405 {e}')
                    time.sleep(0.3)
                time.sleep(2)
                return True
    except Exception as e:
        logger.debug(f"  翻页出错: {e}")
    return False


def collect_company(page, company: dict, days: int = None) -> list:
    logger.info(f"🔎 [{company['group']}] {company['name']}")
    url = f"https://www.tianyancha.com/company/{company['tyc_id']}/jingzhuang"
    page.goto(url, wait_until="commit")
    try:
        page.wait_for_selector("table, [class*='table-container'], [class*='pagination']", timeout=20000)
    except Exception as e:
        logger.warning(f'[collect_company_outer] L421 {e}')
    time.sleep(3)

    if detect_login(page):
        logger.warning("🔴 Cookie 已过期，请重新运行 tyc_login.py")
        return None  # None 表示需要中止
    if detect_anti_crawl(page):
        logger.warning(f"🔴 反爬触发: {company['name']}")
        return []

    cutoff = None
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    all_records = []
    page_num = 1
    while True:
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            logger.warning(f'[collect_company_retry] L441 {e}')
        time.sleep(2)

        records = parse_jingzhuang_page(page, company)
        all_records.extend(records)
        logger.info(f"  第{page_num}页: {len(records)}条（累计{len(all_records)}）")

        # 日期边界
        if cutoff and records:
            if all(r["publish_date"] and r["publish_date"] < cutoff for r in records if r["publish_date"]):
                logger.info(f"  超出{days}天窗口，停止翻页")
                break

        if page_num >= MAX_PAGES:
            break
        if not has_next_page(page):
            break
        if not click_next_page(page, page_num):
            break

        time.sleep(random.uniform(DELAY_BASE, DELAY_BASE + DELAY_JITTER))
        page_num += 1

    return all_records


# ══════════════════════════════════════════════════════════════════════════
#  入库 + MD 保存
# ══════════════════════════════════════════════════════════════════════════

def store(conn: sqlite3.Connection, records: list, cutoff: str = None, dry_run: bool = False) -> dict:
    stats = {"total": 0, "new": 0, "yancheng": 0, "md_saved": 0}
    for r in records:
        stats["total"] += 1
        if cutoff and r["publish_date"] and r["publish_date"] < cutoff:
            continue

        company = r["company"]
        bid_amount, bid_unit = parse_amount(r["bid_amount_text"])
        location = judge_location(r["project_name"], r["procuring_entity"])
        rec_id = make_id(r["project_name"], r["publish_date"], r["procuring_entity"])

        rec = {
            "id": rec_id,
            "company_name": company["name"],
            "company_short": company["short"],
            "company_group": company["group"],
            "project_name": r["project_name"],
            "publish_date": r["publish_date"],
            "procuring_entity": r["procuring_entity"],
            "winner": r["winner"],
            "bid_amount": bid_amount,
            "bid_amount_unit": bid_unit,
            "detail_url": r["detail_url"],
            "project_location": location,
            "page_path": None,
            "collected_at": datetime.now().isoformat(),
        }

        yancheng = is_yancheng(location)
        if yancheng:
            stats["yancheng"] += 1

        if dry_run:
            continue

        # 保存 MD（仅盐城）
        if yancheng:
            try:
                md_path = save_md(rec)
                rec["page_path"] = md_path
                stats["md_saved"] += 1
            except Exception as e:
                logger.warning(f"  MD保存失败: {e}")

        # 入库
        cursor = conn.execute("""
            INSERT OR IGNORE INTO tyc_awards
            (id, company_name, company_short, company_group, project_name,
             publish_date, procuring_entity, winner, bid_amount, bid_amount_unit,
             detail_url, project_location, page_path, collected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rec["id"], rec["company_name"], rec["company_short"], rec["company_group"],
            rec["project_name"], rec["publish_date"], rec["procuring_entity"],
            rec["winner"], rec["bid_amount"], rec["bid_amount_unit"],
            rec["detail_url"], rec["project_location"], rec["page_path"], rec["collected_at"],
        ))
        if cursor.rowcount > 0:
            stats["new"] += 1

    conn.commit()
    return stats


# ══════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="天眼查中标采集 — 13家运营商")
    parser.add_argument("--days",    type=int, default=None, help="时间窗口（天），默认不限")
    parser.add_argument("--company", default=None, help="只采集指定企业（简称），如 苏移集成")
    parser.add_argument("--dry-run", action="store_true", help="不写库/MD，只打印数据")
    args = parser.parse_args()

    # Cookie
    if not COOKIE_PATH.exists():
        logger.error(f"❌ Cookie 不存在: {COOKIE_PATH}")
        logger.error("  请先运行: python3 crawlers/tyc_login.py")
        sys.exit(1)
    with open(COOKIE_PATH) as f:
        cookies = json.load(f)
    logger.info(f"✅ Cookie 已加载 ({len(cookies)} 条)")

    # DB
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)

    companies = ENTERPRISES
    if args.company:
        companies = [e for e in ENTERPRISES if e["short"] == args.company]
        if not companies:
            logger.error(f"❌ 未找到企业: {args.company}")
            sys.exit(1)

    cutoff = None
    if args.days:
        cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        logger.info(f"时间窗口: {cutoff} 至今")

    # P1-2026-07-07: 外层 try/finally 包住 create_context() 防浏览器泄露
    # 预声明 None 避免 close 阶段 NameError（比 'name' in dir() 更安全）
    p = browser = context = page = None
    # 预声明 total_stats 字典；异常路径上保持 0 值，最后汇总日志不会 UnboundLocalError
    total_stats = {"total": 0, "new": 0, "yancheng": 0, "md_saved": 0}
    try:
        p, browser, context = create_context()  # 这行可能被扔异常（cookies 缺失/网络失败）
        context.add_cookies(cookies)
        page = context.new_page()

        for company in companies:
            records = collect_company(page, company, days=args.days)
            if records is None:
                logger.error("Cookie 过期，终止采集")
                break
            if not records:
                continue

            s = store(conn, records, cutoff=cutoff, dry_run=args.dry_run)
            for k in total_stats:
                total_stats[k] += s[k]
            logger.info(
                f"  [{company['short']}] 原始{len(records)} 新增{s['new']} "
                f"盐城{s['yancheng']} MD{s['md_saved']}"
            )

            time.sleep(random.uniform(DELAY_BASE, DELAY_BASE + DELAY_JITTER))
    except Exception as e:
        logger.error(f"采集流程异常: {e}")
    finally:
        # P1-2026-07-07: 每个 close 单独 try，避免前一个失败影响后续释放
        # 原代码只 close browser/p/conn，缺 context.close() → context 句柄泄露
        try:
            if context:
                context.close()
        except Exception as e:
            logger.warning(f"context.close 失败: {e}")
        try:
            if browser:
                browser.close()
        except Exception as e:
            logger.warning(f"browser.close 失败: {e}")
        try:
            if p:
                p.stop()
        except Exception as e:
            logger.warning(f"p.stop 失败: {e}")
        try:
            conn.close()
        except Exception as e:
            logger.warning(f"conn.close 失败: {e}")

    logger.info(
        f"\n📊 汇总: 原始{total_stats['total']} 新增{total_stats['new']} "
        f"盐城{total_stats['yancheng']} MD已保存{total_stats['md_saved']}"
    )

    # 打印盐城统计
    conn2 = sqlite3.connect(DB_PATH)
    rows = conn2.execute("""
        SELECT company_short, company_group,
               COUNT(*) as cnt,
               COALESCE(SUM(bid_amount), 0) as amt
        FROM tyc_awards
        WHERE project_location LIKE '盐城%'
        GROUP BY company_short ORDER BY company_group, company_short
    """).fetchall()
    if rows:
        print("\n=== 天眼查盐城中标汇总 ===")
        for r in rows:
            print(f"  {r[0]:<8} [{r[1]}]  {r[2]:>4}条  {r[3]:>8.1f}万")
    conn2.close()


if __name__ == "__main__":
    main()

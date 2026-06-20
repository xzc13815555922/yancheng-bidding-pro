#!/usr/bin/env python3
"""
盐城市政府采购网 — Playwright 批量详情页补全
- 绕过知道创宇 WAF（requests 返回拦截页面）
- 针对 yancheng_gov 各公告类型的表格/段落结构做专项提取
- 运行后对所有 yancheng_gov 记录补全：发包单位/预算/开标时间/中标单位/中标金额
"""

import asyncio
import json
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
from base import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "yancheng_gov.db"
CONCURRENCY = 2     # 同时开的 page 数量
DELAY = 1.5         # 每页间隔(秒)
BASE_URL = "https://czj.yancheng.gov.cn"

# ─────────────────────────────────────────────
# 通用解析工具
# ─────────────────────────────────────────────

_ORG_SUFFIX = r'公司|集团|局|委员会|中心|学校|医院|协会|基金|银行|事务所|研究院|研究所|大学|学院|政府|事业单位|福利院|养老院|疗养院|托育中心'
_ORG_PAT = re.compile(_ORG_SUFFIX)


def _parse_amount_wan(raw: str) -> Optional[float]:
    """从文本中提取金额(元)。支持万元/亿/元单位。返回元。"""
    if not raw:
        return None
    raw = raw.replace(",", "").replace("，", "")
    m = re.search(r'([\d.]+)\s*(亿|万元|万|元)', raw)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "亿":
        return num * 1e8
    if unit in ("万元", "万"):
        return num * 1e4
    return num


def _parse_datetime(raw: str) -> Optional[str]:
    """归一化日期时间为 'YYYY-MM-DD HH:MM:SS'。"""
    if not raw:
        return None
    raw = re.sub(r'\s+', '', raw)
    patterns = [
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})[时:](\d{1,2})分?(\d{1,2})?',
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})[时:](\d{1,2})',
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, raw)
        if m:
            g = m.groups()
            y, mo, d = g[0], g[1], g[2]
            hh = g[3] if len(g) > 3 and g[3] else "00"
            mm = g[4] if len(g) > 4 and g[4] else "00"
            ss = g[5] if len(g) > 5 and g[5] else "00"
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
    return None


def _extract_org(text: str, max_len: int = 35) -> Optional[str]:
    """从 text 的头部匹配以组织后缀结尾的单位名称。"""
    text = re.sub(r'^[^一-龥a-zA-Z]+', '', text)
    m = re.match(rf'.{{2,{max_len}}}?(?:{_ORG_SUFFIX})', text)
    if m:
        val = m.group(0).strip()
        if 4 < len(val) < max_len + 5:
            return val
    return None


# ─────────────────────────────────────────────
# 各公告类型的专项提取
# ─────────────────────────────────────────────

def _extract_purchaser(soup: BeautifulSoup) -> Optional[str]:
    """
    通用发包单位提取：优先找"采购人信息"节点，再找"单位名称："。
    Strategy 1 ("采购人信息→单位名称：") 精准可信，不强制要求后缀匹配。
    """
    text = soup.get_text('\n')
    # Strategy 1: "采购人信息" + "单位名称：" — trusted pattern, no org-suffix required
    m = re.search(r'采购人信息[\s\S]{0,15}单位名称[：:]\s*([^\n\r]{2,40})', text)
    if m:
        val = m.group(1).strip()
        if 3 < len(val) < 45:
            return val[:40]

    # Strategy 2: any "单位名称：" followed by known org suffix (skip 代理机构 lines)
    for m in re.finditer(r'单位名称[：:]\s*([^\n\r]{2,40})', text):
        val = m.group(1).strip()
        if _ORG_PAT.search(val) and '代理' not in val:
            return val[:40]

    # Strategy 3: fallback general keyword
    for kw in ['采购人：', '发包单位：', '招标人：']:
        m = re.search(re.escape(kw) + r'\s*([^\n\r]{2,40})', text)
        if m:
            val = m.group(1).strip()
            if _ORG_PAT.search(val):
                return val[:40]

    return None


def _extract_budget_tender(soup: BeautifulSoup) -> Optional[Tuple[float, str]]:
    """
    招标公告预算提取："预算金额：56.000000万元..."
    返回 (amount_元, budget_text)
    """
    text = soup.get_text('\n')
    # 预算金额：XXX万元
    m = re.search(r'预算金额[：:]\s*([\d,.]+\s*(?:亿|万元|万|元)[^\n\r]{0,80})', text)
    if m:
        raw = m.group(1).strip()
        amount = _parse_amount_wan(raw)
        if amount and 100 <= amount <= 5e10:
            return amount, raw[:60]
    # 最高限价（有时是替代预算）
    m = re.search(r'最高限价[（(（][如（如有）（如有)][）)]?[：:]\s*([\d,.]+\s*(?:亿|万元|万|元))', text)
    if m:
        raw = m.group(1).strip()
        amount = _parse_amount_wan(raw)
        if amount and 100 <= amount <= 5e10:
            return amount, raw[:60]
    return None


def _extract_open_date_tender(soup: BeautifulSoup) -> Optional[str]:
    """
    招标公告开标时间：
    - "开标时间和地点 2026-07-09 09:00（北京时间）"
    - "2026-07-09 09:00（北京时间）前递交"
    """
    text = soup.get_text('\n')
    # Pattern 1: 开标时间 + nearby datetime
    m = re.search(r'开标时间[^，。\n\r]{0,10}?\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}[日]?\s*\d{1,2}:\d{2})', text)
    if m:
        return _parse_datetime(m.group(1))

    # Pattern 2: date before "前递交投标文件" - this is deadline, treat as open_date for 招标公告
    m = re.search(r'(\d{4}[-年]\d{1,2}[-月]\d{1,2}[日]?\s*\d{1,2}:\d{2})\s*（北京时间）', text)
    if m:
        return _parse_datetime(m.group(1))

    return None


def _extract_award(soup: BeautifulSoup) -> Dict:
    """
    中标/成交公告：从表格提取 winner, winning_amount, purchaser。
    表头: 序号 | 供应商名称 | 社会信用代码 | ... | 中标/成交金额
    """
    result: Dict = {}
    text = soup.get_text('\n')

    # Find the award table by header keywords
    for table in soup.find_all('table'):
        headers = [th.get_text(strip=True) for th in table.find_all('th')]
        if not headers:
            # Also try <td> as headers in first row
            first_row = table.find('tr')
            if first_row:
                headers = [td.get_text(strip=True) for td in first_row.find_all(['td', 'th'])]

        # Check if this is the award table
        has_supplier = any('供应商名称' in h or '中标供应商' in h for h in headers)
        has_amount = any('中标' in h and '金额' in h or '成交' in h and '金额' in h for h in headers)
        if not (has_supplier or has_amount):
            continue

        # Find column indices
        supplier_col = next((i for i, h in enumerate(headers) if '供应商名称' in h or '中标供应商' in h), None)
        amount_col = next((i for i, h in enumerate(headers) if ('中标' in h or '成交' in h) and '金额' in h), None)

        # Get first data row
        rows = table.find_all('tr')
        data_rows = rows[1:] if len(rows) > 1 else []
        if not data_rows:
            continue

        for data_row in data_rows:
            cells = [td.get_text(strip=True) for td in data_row.find_all(['td', 'th'])]
            if len(cells) < 2:
                continue

            if supplier_col is not None and supplier_col < len(cells):
                val = cells[supplier_col]
                if _ORG_PAT.search(val) and len(val) > 3:
                    result['winner'] = val[:50]

            if amount_col is not None and amount_col < len(cells):
                raw = cells[amount_col]
                amount = _parse_amount_wan(raw)
                if amount and 100 <= amount <= 5e10:
                    result['winning_amount'] = amount

            if result.get('winner') or result.get('winning_amount'):
                break

    # Purchaser
    purchaser = _extract_purchaser(soup)
    if purchaser:
        result['purchaser'] = purchaser

    # Also try regex on plain text for winning amount (fallback)
    if 'winning_amount' not in result:
        m = re.search(r'中标[/／]成交金额\s*[\d]*\s*(.{1,30}?(?:\d+)元)', text)
        if m:
            amount = _parse_amount_wan(m.group(0))
            if amount and 100 <= amount <= 5e10:
                result['winning_amount'] = amount

    return result


def _extract_intention(soup: BeautifulSoup) -> Dict:
    """
    采购意向：从表格提取 budget（采购预算(万元) 列），purchaser 从标题/文本。
    """
    result: Dict = {}
    text = soup.get_text('\n')

    # Find table with 采购预算 column
    for table in soup.find_all('table'):
        all_rows = table.find_all('tr')
        if not all_rows:
            continue

        # Get header row
        header_cells = all_rows[0].find_all(['th', 'td'])
        headers = [c.get_text(strip=True) for c in header_cells]

        budget_col = None
        for i, h in enumerate(headers):
            h_clean = re.sub(r'\s+', '', h)
            if '采购预算' in h_clean:
                budget_col = i
                break

        if budget_col is None:
            continue

        # Sum up all budget values in that column (multiple projects in one page)
        total = 0.0
        count = 0
        for row in all_rows[1:]:
            cells = row.find_all(['td', 'th'])
            if budget_col < len(cells):
                raw = cells[budget_col].get_text(strip=True)
                if raw and re.search(r'\d', raw):
                    try:
                        v = float(re.sub(r'[^\d.]', '', raw))
                        if 0 < v < 1e7:  # assume 万元, max 1000亿
                            total += v * 1e4  # convert 万 to 元
                            count += 1
                    except Exception:
                        pass

        if count > 0:
            result['budget'] = total
            result['budget_unit'] = '元'
            result['budget_text'] = f"{total/1e4:.4f}万元(共{count}项)"
        break  # found the table, stop

    # Purchaser: from organization name in title/header text
    # Title often starts with "XX单位2026年N月..."
    title_m = re.search(r'^([^，,。\n\r]{3,30}?(?:政府|局|委|中心|学校|医院|办事处|事务所))',
                        text.strip())
    if title_m:
        result['purchaser'] = title_m.group(1).strip()
    else:
        purchaser = _extract_purchaser(soup)
        if purchaser:
            result['purchaser'] = purchaser

    return result


def _extract_tender(soup: BeautifulSoup) -> Dict:
    """
    招标公告、竞争性谈判、询价等：提取 budget, open_date, purchaser。
    """
    result: Dict = {}

    budget_res = _extract_budget_tender(soup)
    if budget_res:
        result['budget'] = budget_res[0]
        result['budget_unit'] = '元'
        result['budget_text'] = budget_res[1]

    open_date = _extract_open_date_tender(soup)
    if open_date:
        result['open_date'] = open_date

    purchaser = _extract_purchaser(soup)
    if purchaser:
        result['purchaser'] = purchaser

    return result


# ─────────────────────────────────────────────
# Playwright 批量抓取
# ─────────────────────────────────────────────

def parse_detail(html: str, notice_type: str, detail_url: str) -> Dict:
    """根据公告类型调用专项提取函数。"""
    soup = BeautifulSoup(html, 'html.parser')
    # Get the article content area
    content = (soup.find('div', class_='bt-content') or
               soup.find('div', id='content') or
               soup.find('article') or
               soup.body)
    if content is None:
        content = soup

    result: Dict = {}

    if notice_type == 'award':
        result = _extract_award(content)
    elif notice_type == 'intention':
        result = _extract_intention(content)
    elif notice_type in ('tender', 'other'):
        result = _extract_tender(content)
    else:
        # requirement, other
        result = _extract_tender(content)
        result.pop('open_date', None)

    # Detect WAF block page
    page_text = soup.get_text()[:200]
    if '知道创宇' in page_text or '云防御' in page_text or 'client:' in page_text:
        logger.warning(f"WAF block detected: {detail_url[-50:]}")
        return {}

    return result


async def fetch_page(page: Page, url: str, referer: str = BASE_URL + "/") -> str:
    """Playwright 抓单页 HTML。"""
    await page.goto(url, referer=referer, wait_until='domcontentloaded', timeout=20000)
    await asyncio.sleep(0.5)
    return await page.content()


async def enrich_batch(records: List[Dict], dry_run: bool = False):
    """批量补全一组记录。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
        )
        # Open a few pages for concurrency
        pages = [await ctx.new_page() for _ in range(CONCURRENCY)]

        sem = asyncio.Semaphore(CONCURRENCY)
        page_pool = asyncio.Queue()
        for p in pages:
            await page_pool.put(p)

        ok = fail = waf = 0

        async def process_one(rec: Dict):
            nonlocal ok, fail, waf
            url = rec['detail_url']
            ntype = rec['notice_type']
            rid = rec['id']

            pg = await page_pool.get()
            try:
                try:
                    html = await fetch_page(pg, url)
                except Exception as e:
                    logger.debug(f"  fetch failed {url[-40:]}: {e}")
                    fail += 1
                    return

                fields = parse_detail(html, ntype, url)
                if not fields:
                    waf += 1
                    return

                if dry_run:
                    logger.info(f"  [DRY] {ntype} {url[-40:]}: {fields}")
                    ok += 1
                    return

                sets = [f"{k}=?" for k in fields]
                vals = list(fields.values())
                sets.append("detail_fetched=?")
                vals.append(1)
                vals.append(rid)
                conn.execute(f"UPDATE notices SET {', '.join(sets)} WHERE id=?", vals)
                conn.commit()
                ok += 1
                logger.debug(f"  OK {ntype} {url[-40:]}: {list(fields.keys())}")

            finally:
                await page_pool.put(pg)
                await asyncio.sleep(DELAY)

        tasks = [process_one(rec) for rec in records]
        # Process in batches
        for i in range(0, len(tasks), CONCURRENCY * 2):
            batch = tasks[i:i + CONCURRENCY * 2]
            await asyncio.gather(*batch)
            logger.info(f"  Progress: {min(i + CONCURRENCY*2, len(tasks))}/{len(tasks)} "
                        f"ok={ok} fail={fail} waf={waf}")

        await browser.close()

    conn.close()
    return {'ok': ok, 'fail': fail, 'waf': waf}


def get_records_to_process(force_all: bool = False) -> List[Dict]:
    """
    获取需要补全的记录。
    force_all=True: 所有记录（包括 detail_fetched=1 但字段不全的）
    force_all=False: 只处理 detail_fetched IS NULL 的新记录
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    if force_all:
        rows = conn.execute("""
            SELECT id, detail_url, notice_type FROM notices
            WHERE detail_url IS NOT NULL
            ORDER BY notice_type, publish_date DESC
        """).fetchall()
    else:
        # Records missing key fields
        rows = conn.execute("""
            SELECT id, detail_url, notice_type FROM notices
            WHERE detail_url IS NOT NULL
              AND (
                detail_fetched IS NULL
                OR (notice_type='award'  AND (winner IS NULL OR winning_amount IS NULL))
                OR (notice_type='tender' AND (budget IS NULL OR open_date IS NULL))
                OR (notice_type='intention' AND budget IS NULL)
                OR purchaser IS NULL
              )
            ORDER BY notice_type, publish_date DESC
        """).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def print_stats():
    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    print(f"\n=== yancheng_gov 字段填充率 (共{total}条) ===")
    for col, label in [
        ('purchaser', '发包单位'),
        ('budget', '预算'),
        ('open_date', '开标时间'),
        ('winner', '中标单位'),
        ('winning_amount', '中标金额'),
    ]:
        n = conn.execute(f"SELECT COUNT(*) FROM notices WHERE {col} IS NOT NULL").fetchone()[0]
        print(f"  {label}: {n}/{total} ({n*100//total if total else 0}%)")

    # By type
    print()
    for ntype in ['award', 'tender', 'intention', 'requirement', 'other']:
        n = conn.execute(f"SELECT COUNT(*) FROM notices WHERE notice_type='{ntype}'").fetchone()[0]
        pc = conn.execute(f"SELECT COUNT(*) FROM notices WHERE notice_type='{ntype}' AND purchaser IS NOT NULL").fetchone()[0]
        bu = conn.execute(f"SELECT COUNT(*) FROM notices WHERE notice_type='{ntype}' AND budget IS NOT NULL").fetchone()[0]
        od = conn.execute(f"SELECT COUNT(*) FROM notices WHERE notice_type='{ntype}' AND open_date IS NOT NULL").fetchone()[0]
        wi = conn.execute(f"SELECT COUNT(*) FROM notices WHERE notice_type='{ntype}' AND winner IS NOT NULL").fetchone()[0]
        wa = conn.execute(f"SELECT COUNT(*) FROM notices WHERE notice_type='{ntype}' AND winning_amount IS NOT NULL").fetchone()[0]
        print(f"  {ntype:<12}: n={n:3d} purchaser={pc:3d} budget={bu:3d} open_date={od:3d} winner={wi:3d} win_amt={wa:3d}")

    conn.close()


async def main(dry_run: bool = False, force_all: bool = False, limit: int = 0):
    print_stats()
    records = get_records_to_process(force_all=force_all)
    if limit:
        records = records[:limit]
    logger.info(f"待补全: {len(records)} 条 (force_all={force_all})")

    if not records:
        logger.info("无需补全")
        return

    result = await enrich_batch(records, dry_run=dry_run)
    logger.info(f"完成: ok={result['ok']} fail={result['fail']} waf={result['waf']}")
    print_stats()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='不写入DB，只打印结果')
    parser.add_argument('--force-all', action='store_true', help='重新处理所有记录（包括已补全的）')
    parser.add_argument('--limit', type=int, default=0, help='限制处理条数（调试用）')
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run, force_all=args.force_all, limit=args.limit))

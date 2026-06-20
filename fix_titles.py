#!/usr/bin/env python3
"""修复 yancheng_gov 乱码项目名称：从详情页 <title> 或 <h1> 提取真实标题"""
import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
from base import DATA_DIR

DB_PATH = DATA_DIR / "yancheng_gov.db"
CONCURRENCY = 3
DELAY = 1.2


def get_bad_records():
    db = sqlite3.connect(str(DB_PATH))
    rows = db.execute("SELECT id, project_name, detail_url FROM notices").fetchall()
    db.close()
    bad = []
    for rid, name, url in rows:
        name = name or ''
        if not re.search(r'[一-鿿]', name) or len(name) < 4 or '<' in name:
            if url:
                bad.append((rid, url))
    return bad


def extract_title(html: str, url: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')

    # WAF check
    page_text = soup.get_text()[:300]
    if '知道创宇' in page_text or 'client:' in page_text:
        return ''

    # Try <title> tag
    title_tag = soup.find('title')
    if title_tag:
        raw = title_tag.get_text(strip=True)
        # Strip site suffix like "—盐城市财政局" or "- 盐城市..."
        raw = re.sub(r'\s*[-—–]\s*盐城.*$', '', raw).strip()
        raw = re.sub(r'\s*[-—–]\s*政府采购.*$', '', raw).strip()
        # Strip leading breadcrumb: "盐城市财政局 XX公告 真正标题" → 取最后一个公告类型词之后的内容
        raw = re.sub(r'^.*?(?:合同公告|招标公告|中标公告|成交公告|采购意向|更正公告|终止公告|询价公告|竞争性[谈磋]判?公告|入围公告|征集公告|需求公示|单一来源公示)\s*', '', raw).strip()
        if raw and len(raw) >= 4 and re.search(r'[一-鿿]', raw):
            return raw[:100]

    # Try h1/h2 in article content
    content = soup.find('div', class_='bt-content') or soup.find('article') or soup.body
    if content:
        for tag in content.find_all(['h1', 'h2', 'h3']):
            t = tag.get_text(strip=True)
            if t and len(t) >= 4 and re.search(r'[一-鿿]', t):
                return t[:100]

    return ''


async def fix_titles(dry_run: bool = False):
    records = get_bad_records()
    print(f"需修复: {len(records)} 条")
    if not records:
        return

    conn = sqlite3.connect(str(DB_PATH))
    ok = fail = waf = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        pages = [await ctx.new_page() for _ in range(CONCURRENCY)]
        page_pool = asyncio.Queue()
        for p in pages:
            await page_pool.put(p)

        async def process(rid, url):
            nonlocal ok, fail, waf
            pg = await page_pool.get()
            try:
                try:
                    await pg.goto(url, wait_until='domcontentloaded', timeout=20000)
                    await asyncio.sleep(0.3)
                    html = await pg.content()
                except Exception as e:
                    print(f"  FAIL {url[-40:]}: {e}")
                    fail += 1
                    return

                title = extract_title(html, url)
                if not title:
                    waf += 1
                    print(f"  WAF/empty {url[-40:]}")
                    return

                if dry_run:
                    print(f"  [DRY] {url[-40:]}: '{title}'")
                else:
                    conn.execute("UPDATE notices SET project_name=? WHERE id=?", (title, rid))
                    conn.commit()
                ok += 1
                print(f"  OK: '{title[:60]}'")
            finally:
                await page_pool.put(pg)
                await asyncio.sleep(DELAY)

        tasks = [process(rid, url) for rid, url in records]
        for i in range(0, len(tasks), CONCURRENCY * 2):
            batch = tasks[i:i + CONCURRENCY * 2]
            await asyncio.gather(*batch)
            print(f"  进度: {min(i+CONCURRENCY*2, len(tasks))}/{len(tasks)} ok={ok} fail={fail} waf={waf}")

        await browser.close()

    conn.close()
    print(f"\n完成: ok={ok} fail={fail} waf={waf}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    asyncio.run(fix_titles(dry_run=args.dry_run))

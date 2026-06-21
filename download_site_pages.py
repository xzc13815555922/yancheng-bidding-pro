#!/usr/bin/env python3
"""
批量下载各站点详情页，转换为 Markdown 保存本地。
- 保存目录: data/pages/{site}/{id}.md
- ycggzy: 从 raw_json.content 提取（无需请求网络）
- 其他站: 请求 detail_url，html2text 转 Markdown
- 断点续传：已有文件且 DB 已记录 page_path 则跳过
- DB 各站新增 page_path 列
"""
import json
import logging
import sqlite3
import time
from pathlib import Path

import html2text
import requests
from bs4 import BeautifulSoup

_ILLEGAL = re.compile(r'[/\\:*?"<>|]')
_MULTI_  = re.compile(r'_+')


def _safe_name(title: str) -> str:
    t = title.strip()[:60]
    t = _ILLEGAL.sub('_', t)
    t = _MULTI_.sub('_', t).strip('_')
    return t or "unnamed"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
PAGE_DIR = DATA_DIR / "pages"

SITES = [
    "yancheng_gov",
    "sufu",
    "yueda",
    "dongfang",
    "dushi",
    "jscn",
    "chennan",
    "kaifaqu",
    "bigdata",
    "jingkai",
]

# 已知 GBK 编码站点（dongfang 实际是 UTF-8，用 apparent_encoding 检测）
GBK_SITES: set = set()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

_h2t = html2text.HTML2Text()
_h2t.ignore_links    = False
_h2t.ignore_images   = True
_h2t.body_width      = 0
_h2t.single_line_break = True


def _html_to_md(html: str) -> str:
    """提取主内容区域并转换为 Markdown。"""
    soup = BeautifulSoup(html, "html.parser")
    # 尝试找主内容区
    for sel in [".TRS_Editor", ".article-content", ".detail-content",
                "#vsb_content", ".content_box", ".art-content", "article",
                ".main-content", "#content"]:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 50:
            return _h2t.handle(str(el)).strip()
    # 兜底：全页转换
    return _h2t.handle(html).strip()


def _add_page_path_col(conn: sqlite3.Connection):
    try:
        conn.execute("ALTER TABLE notices ADD COLUMN page_path TEXT")
        conn.commit()
    except Exception:
        pass


def download_site(site: str, sess: requests.Session):
    db_path  = DATA_DIR / f"{site}.db"
    site_dir = PAGE_DIR / site
    site_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _add_page_path_col(conn)

    rows = conn.execute(
        "SELECT id, project_name, detail_url, page_path FROM notices WHERE detail_url IS NOT NULL"
    ).fetchall()
    logger.info(f"[{site}] {len(rows)} 条有 detail_url")

    used: dict[str, int] = {}
    ok = skip = fail = 0
    for row in rows:
        rid      = row["id"]
        url      = row["detail_url"]
        existing = row["page_path"]
        title    = row["project_name"] or rid
        base     = _safe_name(title)
        if base in used:
            used[base] += 1
            base = f"{base}_{used[base]}"
        else:
            used[base] = 1
        md_file  = site_dir / f"{base}.md"

        if existing and Path(existing).exists():
            skip += 1
            continue

        try:
            encoding = "gbk" if site in GBK_SITES else None
            r = sess.get(url, timeout=15, headers=HEADERS)
            if encoding:
                r.encoding = encoding
            elif r.encoding and r.encoding.lower() in ("iso-8859-1", "windows-1252"):
                r.encoding = r.apparent_encoding

            md = _html_to_md(r.text)
            if len(md.strip()) < 30:
                fail += 1
                continue

            md_file.write_text(
                f"# {url}\n\n{md}", encoding="utf-8"
            )
            conn.execute("UPDATE notices SET page_path=? WHERE id=?", (str(md_file), rid))
            conn.commit()
            ok += 1
            time.sleep(0.3)

        except Exception as e:
            logger.warning(f"  [{site}] {url[:60]} 失败: {e}")
            fail += 1
            continue

    conn.close()
    logger.info(f"[{site}] 下载={ok}  跳过={skip}  失败={fail}")
    return ok, skip, fail


def download_ycggzy():
    """ycggzy 是 SPA，从 raw_json.content 提取，无需网络请求。"""
    site     = "ycggzy"
    db_path  = DATA_DIR / f"{site}.db"
    site_dir = PAGE_DIR / site
    site_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _add_page_path_col(conn)

    rows = conn.execute(
        "SELECT id, project_name, raw_json, page_path FROM notices WHERE raw_json IS NOT NULL"
    ).fetchall()

    used: dict[str, int] = {}
    ok = skip = no_content = 0
    for row in rows:
        rid      = row["id"]
        existing = row["page_path"]
        title    = row["project_name"] or rid
        base     = _safe_name(title)
        if base in used:
            used[base] += 1
            base = f"{base}_{used[base]}"
        else:
            used[base] = 1
        md_file  = site_dir / f"{base}.md"

        if existing and md_file.exists():
            skip += 1
            continue

        try:
            rj      = json.loads(row["raw_json"] or "{}")
            content = rj.get("content") or ""
            if not content or len(content.strip()) < 20:
                no_content += 1
                continue
            md = _h2t.handle(content).strip()
            if len(md) < 20:
                no_content += 1
                continue
            md_file.write_text(f"# ycggzy/{rid}\n\n{md}", encoding="utf-8")
            conn.execute("UPDATE notices SET page_path=? WHERE id=?", (str(md_file), rid))
            ok += 1
        except Exception:
            no_content += 1

    conn.commit()
    conn.close()
    logger.info(f"[ycggzy] 保存={ok}  跳过={skip}  无content={no_content}")
    return ok


def main(sites=None):
    sess = requests.Session()
    sess.headers.update(HEADERS)

    total_ok = 0

    # ycggzy 本地提取
    if not sites or "ycggzy" in sites:
        total_ok += download_ycggzy()

    # 其他站点
    for site in SITES:
        if sites and site not in sites:
            continue
        ok, skip, fail = download_site(site, sess)
        total_ok += ok

    # 汇总
    all_pages = sum(len(list((PAGE_DIR / s).glob("*.md")))
                    for s in (SITES + ["ycggzy"]) if (PAGE_DIR / s).exists())
    total_size = sum(f.stat().st_size for f in PAGE_DIR.rglob("*.md"))
    logger.info(f"\n=== 完成 ===")
    logger.info(f"  共 {all_pages} 个 MD 文件  总大小: {total_size/1024/1024:.1f} MB")
    logger.info(f"  保存目录: {PAGE_DIR}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--site", nargs="+", help="只处理指定站点")
    args = p.parse_args()
    main(sites=args.site)

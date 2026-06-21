#!/usr/bin/env python3
"""
jszbcg PDF 批量下载
- 遍历所有记录，调 Detail API 取 signPdfUrl，下载保存到 data/pdfs/jszbcg/
- 文件名: {bulletinID}.pdf
- 下载路径写回 DB notices.pdf_path
- 已下载的跳过（断点续传）
"""
import json
import logging
import sqlite3
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR   = Path(__file__).parent / "data"
DB_PATH    = DATA_DIR / "jszbcg.db"
PDF_DIR    = DATA_DIR / "pdfs" / "jszbcg"
PDF_DIR.mkdir(parents=True, exist_ok=True)

DETAIL_API = "https://api.jszbtb.com/DataGatewayApi/BulletinDetail/{bid_id}"
HEADERS    = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer":    "https://www.jszbcg.com/",
    "Accept":     "application/json",
}


def download_all():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, raw_json, pdf_path FROM notices ORDER BY publish_date DESC"
    ).fetchall()
    logger.info(f"共 {len(rows)} 条记录")

    sess = requests.Session()
    sess.headers.update(HEADERS)

    ok = skip = no_pdf = fail = 0

    for i, row in enumerate(rows):
        rid      = row["id"]
        existing = row["pdf_path"]
        raw      = json.loads(row["raw_json"] or "{}")
        bid_id   = raw.get("bulletinID", "")

        if not bid_id:
            skip += 1
            continue

        pdf_file = PDF_DIR / f"{bid_id}.pdf"

        # 断点续传：已有文件且 DB 已记录路径则跳过
        if existing and pdf_file.exists():
            skip += 1
            continue

        # 1. 获取 PDF URL
        try:
            r     = sess.get(DETAIL_API.format(bid_id=bid_id), timeout=10)
            data  = r.json().get("data") or {}
            pdf_url = data.get("signPdfUrl", "")
        except Exception as e:
            logger.warning(f"[{i+1}/{len(rows)}] Detail API 失败: {e}")
            fail += 1
            continue

        if not pdf_url:
            no_pdf += 1
            if (i + 1) % 50 == 0:
                logger.info(f"[{i+1}/{len(rows)}] ok={ok} skip={skip} no_pdf={no_pdf} fail={fail}")
            continue

        # 2. 下载 PDF
        try:
            pr        = sess.get(pdf_url, timeout=30)
            pdf_bytes = pr.content
        except Exception as e:
            logger.warning(f"[{i+1}/{len(rows)}] PDF 下载失败: {e}")
            fail += 1
            continue

        if len(pdf_bytes) < 1000:
            no_pdf += 1
            continue

        # 3. 保存
        pdf_file.write_bytes(pdf_bytes)

        # 4. 写回 DB
        conn.execute("UPDATE notices SET pdf_path=? WHERE id=?", (str(pdf_file), rid))
        conn.commit()
        ok += 1

        if ok % 20 == 0 or (i + 1) % 100 == 0:
            logger.info(f"[{i+1}/{len(rows)}] 已下载={ok} 跳过={skip} 无PDF={no_pdf} 失败={fail}")

        time.sleep(0.2)

    conn.close()

    # 统计
    total_size = sum(f.stat().st_size for f in PDF_DIR.glob("*.pdf"))
    count      = len(list(PDF_DIR.glob("*.pdf")))
    logger.info(f"\n=== 完成 ===")
    logger.info(f"  下载: {ok}  跳过(已有): {skip}  无PDF: {no_pdf}  失败: {fail}")
    logger.info(f"  本地PDF: {count} 个  总大小: {total_size/1024/1024:.1f} MB")
    logger.info(f"  保存目录: {PDF_DIR}")


if __name__ == "__main__":
    download_all()

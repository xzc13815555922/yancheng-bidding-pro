#!/usr/bin/env python3
"""
jszbcg OCR 补全 — 对图片型 PDF 批量 OCR，提取预算/中标单位/中标金额。

流程：
  1. 从 raw_json 取 bulletinID
  2. 调用 https://api.jszbtb.com/DataGatewayApi/BulletinDetail/{id} 取 signPdfUrl
  3. PyMuPDF 将 PDF 每页渲染成 2x 分辨率 PNG
  4. PaddleOCR 识别，拼接文本
  5. 正则解析 winner / winning_amount / budget
  6. UPDATE notices
"""
import json
import logging
import re
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import fitz  # PyMuPDF
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "jszbcg.db"

DETAIL_API = "https://api.jszbtb.com/DataGatewayApi/BulletinDetail/{bid_id}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.jszbcg.com/",
    "Accept": "application/json",
}

_ocr = None


def _get_ocr():
    global _ocr
    if _ocr is None:
        logger.info("初始化 PaddleOCR（首次加载模型）...")
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            lang="ch",
        )
        logger.info("PaddleOCR 就绪")
    return _ocr


MAX_PAGES = 1       # 只处理第1页（winner/budget 均在首页）
OCR_TIMEOUT = 60   # 单页OCR超时秒数，超时跳过该记录


def _ocr_predict_with_timeout(ocr, img_path: str, timeout: int = OCR_TIMEOUT):
    """在子线程中运行 ocr.predict，超时则抛 TimeoutError。"""
    result = [None]
    exc = [None]

    def _run():
        try:
            result[0] = ocr.predict(img_path)
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        raise TimeoutError(f"ocr.predict 超过 {timeout}s 未返回")
    if exc[0]:
        raise exc[0]
    return result[0]


def ocr_pdf(pdf_bytes: bytes) -> str:
    """提取 PDF 文本：先尝试原生文本层，不足时才 OCR。"""
    texts = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    image_pages = []

    for page_num in range(min(len(doc), MAX_PAGES)):
        page = doc[page_num]
        native = page.get_text().strip()
        if len(native) > 30:
            texts.append(native)
        else:
            image_pages.append((page_num, page))

    native_text = " ".join(texts)
    if image_pages and len(native_text) < 100:
        ocr = _get_ocr()
        with tempfile.TemporaryDirectory() as tmpdir:
            for page_num, page in image_pages:
                mat = fitz.Matrix(1.0, 1.0)
                pix = page.get_pixmap(matrix=mat)
                img_path = str(Path(tmpdir) / f"page_{page_num}.png")
                pix.save(img_path)
                result = _ocr_predict_with_timeout(ocr, img_path)
                if result:
                    texts.extend(result[0].get("rec_texts", []))

    doc.close()
    return " ".join(texts)


def _parse_ocr_text(text: str, notice_type: str) -> dict:
    """从 OCR 纯文本中提取目标字段。"""
    result = {}
    t = re.sub(r"\s+", "", text)  # 去空白后搜索

    # ── 中标单位 / 成交供应商 ──
    _SUFFIX = r"(?:有限责任公司|股份有限公司|有限公司|集团有限公司|集团|公司|局|中心|院|处|所|协会|委员会|学校|医院|银行|基金|事务所)"
    if notice_type == "award":
        # "中标候选人第1名：江苏金呈建设有限公司，..."
        patterns = [
            rf"中标候选人第[1１一]名[：:]([^，,。；\n]{{4,40}}?{_SUFFIX})",
            rf"中标候选人[：:]([^，,。；\n]{{4,40}}?{_SUFFIX})",
            rf"中标人[：:]([^，,。；\n]{{4,40}}?{_SUFFIX})",
            rf"成交供应商[：:]([^，,。；\n]{{4,40}}?{_SUFFIX})",
            rf"中标单位[：:]([^，,。；\n]{{4,40}}?{_SUFFIX})",
        ]
        for pat in patterns:
            m = re.search(pat, t)
            if m:
                result["winner"] = m.group(1).strip()[:50]
                break

        # ── 中标/成交金额 ──
        amt_patterns = [
            r"投标报价金额[：:]([\d.]+)\s*万元",
            r"中标价格?[：:]([\d,.]+)\s*万元",
            r"成交金额[：:]([\d,.]+)\s*万元",
            r"中标金额[：:]([\d,.]+)\s*万元",
            r"投标报价金额[：:]([\d,.]+)\s*元",
            r"中标价格?[：:]([\d,.]+)\s*元",
            r"成交金额[：:]([\d,.]+)\s*元",
        ]
        for pat in amt_patterns:
            m = re.search(pat, t)
            if m:
                raw = m.group(1).replace(",", "").replace("，", "")
                try:
                    v = float(raw)
                    if "万元" in pat:
                        v *= 1e4
                    if 100 <= v <= 5e10:
                        result["winning_amount"] = v
                        break
                except ValueError:
                    pass

    # ── 预算 / 控制价（tender 和 award 均尝试）──
    budget_patterns = [
        r"最高限价[（(]不含税[)）]?[：:]([\d.]+)\s*万元",
        r"最高限价[：:\s约]{0,3}([\d.]+)\s*万元",
        r"控制价[：:\s约]{0,3}([\d.]+)\s*万元",
        r"预算金额[：:\s约]{0,3}([\d.]+)\s*万元",
        r"采购预算[：:\s约]{0,3}([\d.]+)\s*万元",
        r"采购限价[：:\s约]{0,3}([\d.]+)\s*万元",
        r"项目预算[：:\s约]{0,3}([\d.]+)\s*万元",
        r"资金[：:]\s*[\d.]+\s*万元[，,][^，。]{0,20}([\d.]+)\s*万元",
        r"最高限价[：:\s约]{0,3}([\d.]+)\s*元",
        r"控制价[：:\s约]{0,3}([\d.]+)\s*元",
        r"采购限价[：:\s约]{0,3}([\d.]+)\s*元",
        r"国有资金[：:]([\d.]+)万元",
    ]
    for pat in budget_patterns:
        m = re.search(pat, t)
        if m:
            raw = m.group(1).replace(",", "")
            try:
                v = float(raw)
                if "万元" in pat:
                    v *= 1e4
                if 100 <= v <= 5e10:
                    result["budget"] = v
                    result["budget_unit"] = "元"
                    result["budget_text"] = m.group(0)[:40]
                    break
            except ValueError:
                pass

    return result


def enrich_jszbcg_ocr(limit: int = 0, force: bool = False):
    """
    对 jszbcg 所有记录做 OCR 补全。
    force=True 时对 winner IS NOT NULL 的也重跑（用于测试）。
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Award records: only if winner is missing (award notices never contain budget)
    # Tender records: budget OR purchaser missing (avoids re-skipping records enriched before purchaser extraction was added)
    # Other records: only if budget is missing
    where = "" if force else """WHERE (
        (notice_type='award' AND (winner IS NULL OR purchaser IS NULL))
        OR (notice_type='tender' AND (budget IS NULL OR purchaser IS NULL))
        OR (notice_type NOT IN ('award','tender') AND (budget IS NULL OR purchaser IS NULL))
    )"""
    limit_clause = f" LIMIT {limit}" if limit else ""
    # award records first (winner extraction), then tender (budget), then other
    order = " ORDER BY CASE notice_type WHEN 'award' THEN 0 WHEN 'tender' THEN 1 ELSE 2 END"
    rows = conn.execute(
        f"SELECT id, notice_type, raw_json FROM notices {where}{order}{limit_clause}"
    ).fetchall()
    logger.info(f"待 OCR 补全: {len(rows)} 条")

    sess = requests.Session()
    sess.headers.update(HEADERS)

    ok = skip = fail = 0
    total = len(rows)

    for i, row in enumerate(rows):
        rid = row["id"]
        ntype = row["notice_type"]
        raw = json.loads(row["raw_json"] or "{}")
        bid_id = raw.get("bulletinID", "")

        logger.info(f"[{i+1}/{total}] {bid_id[:20]}.. {ntype}")

        if not bid_id:
            logger.info(f"  → 跳过: 无bulletinID")
            skip += 1
            continue

        # ── 1. 获取 PDF（优先本地，否则调 Detail API 下载）──
        existing_pdf = conn.execute(
            "SELECT pdf_path FROM notices WHERE id=?", (rid,)
        ).fetchone()
        local_pdf = existing_pdf["pdf_path"] if existing_pdf and existing_pdf["pdf_path"] else None
        local_path = Path(local_pdf) if local_pdf else None

        if local_path and local_path.exists() and local_path.stat().st_size > 1000:
            try:
                pdf_bytes = local_path.read_bytes()
                tender_name = ""  # 已有本地文件，跳过 Detail API
            except Exception as e:
                logger.info(f"  → 读本地PDF失败: {e}")
                fail += 1
                continue
        else:
            try:
                r = sess.get(DETAIL_API.format(bid_id=bid_id), timeout=10)
                detail_data = r.json().get("data") or {}
                pdf_url = detail_data.get("signPdfUrl", "")
                tender_name = detail_data.get("tenderName") or ""
            except Exception as e:
                logger.info(f"  → Detail API 失败: {e}")
                fail += 1
                continue

            # 从 tenderName 回填 purchaser
            if tender_name:
                conn.execute(
                    "UPDATE notices SET purchaser=COALESCE(purchaser, ?) WHERE id=?",
                    (tender_name[:50], rid)
                )
                conn.commit()

            if not pdf_url:
                logger.info(f"  → 跳过: 无PDF链接")
                skip += 1
                continue

            try:
                pr = sess.get(pdf_url, timeout=30)
                pdf_bytes = pr.content
                # 保存到本地
                try:
                    from pathlib import Path as _P
                    _pdf_dir = _P(__file__).parent / "data" / "pdfs" / "jszbcg"
                    _pdf_dir.mkdir(parents=True, exist_ok=True)
                    _pf = _pdf_dir / f"{bid_id}.pdf"
                    _pf.write_bytes(pdf_bytes)
                    conn.execute("UPDATE notices SET pdf_path=? WHERE id=?", (str(_pf), rid))
                    conn.commit()
                except Exception:
                    pass
            except Exception as e:
                logger.info(f"  → PDF下载失败: {e}")
                fail += 1
                continue

        if len(pdf_bytes) < 5000:
            logger.info(f"  → 跳过: PDF过小({len(pdf_bytes)}B)")
            skip += 1
            continue

        # ── 3. OCR ──
        logger.info(f"  → 开始OCR ({len(pdf_bytes)//1024}KB)")
        try:
            text = ocr_pdf(pdf_bytes)
        except TimeoutError as e:
            logger.info(f"  → OCR超时跳过: {e}")
            skip += 1
            continue
        except Exception as e:
            logger.info(f"  → OCR失败: {e}")
            fail += 1
            continue

        if not text.strip():
            logger.info(f"  → OCR空文本，跳过")
            skip += 1
            continue

        # ── 4. 解析（OCR正则 + parse_html_detail 双引擎，互补缺失字段）──
        fields = _parse_ocr_text(text, ntype)
        # 用 parse_html_detail 补充 _parse_ocr_text 未提取到的字段
        try:
            from enrich_details import parse_html_detail as _phd
            generic = _phd(text, ntype)
            for key in ("budget", "budget_unit", "budget_text", "winner", "winning_amount", "open_date", "purchaser"):
                if key not in fields and generic.get(key):
                    fields[key] = generic[key]
        except Exception:
            pass
        if ntype == "award" and "winner" not in fields:
            fields["winner"] = ""
        if not fields:
            logger.info(f"  → 解析无字段，跳过 text[:60]={text[:60]!r}")
            skip += 1
            continue

        # ── 5. 更新 DB（只写非 NULL 字段，保护现有值）──
        sets = [f"{k}=?" for k in fields]
        vals = list(fields.values()) + [rid]
        conn.execute(f"UPDATE notices SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()
        ok += 1

        logger.info(
            f"  [{ok}] {bid_id[:16]}.. {ntype} "
            f"winner={fields.get('winner','')[:20]} "
            f"budget={fields.get('budget','')}"
        )
        time.sleep(0.3)

    conn.close()

    # ── 结果统计 ──
    conn2 = sqlite3.connect(str(DB_PATH))
    total = conn2.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    print(f"\n=== jszbcg OCR 补全完成 ===")
    for col, label in [
        ("purchaser", "发包单位"),
        ("budget", "预算"),
        ("open_date", "开标时间"),
        ("winner", "中标单位"),
        ("winning_amount", "中标金额"),
    ]:
        n = conn2.execute(
            f"SELECT COUNT(*) FROM notices WHERE {col} IS NOT NULL AND {col} != ''"
        ).fetchone()[0]
        print(f"  {label}: {n}/{total} ({n*100//total}%)")
    conn2.close()
    print(f"\n更新: {ok}  跳过(无PDF): {skip}  失败: {fail}")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="jszbcg 图片 PDF OCR 补全")
    p.add_argument("--limit", type=int, default=0, help="最多处理条数（0=全部）")
    p.add_argument("--force", action="store_true", help="强制重跑已有 winner 的记录")
    args = p.parse_args()
    enrich_jszbcg_ocr(limit=args.limit, force=args.force)
    import subprocess, sys as _sys
    from pathlib import Path as _Path
    print("\n[同步] 重建 unified.db ...")
    subprocess.run([_sys.executable, str(_Path(__file__).parent / "build_unified.py")], check=False)

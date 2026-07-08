#!/usr/bin/env python3
"""
将 jszbcg 本地 PDF 批量 OCR 转成 MD 文件，按项目名称命名。
断点续传：已有 page_path 的跳过。

用法：
    python3 convert_jszbcg_pdfs_to_md.py [--limit N]
"""
import logging
import argparse
import re
import sqlite3
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DB_PATH  = DATA_DIR / "jszbcg.db"
MD_DIR   = DATA_DIR / "pages" / "jszbcg"

def _safe_name(title: str) -> str:
    name = re.sub(r'[\\/*?:"<>|\r\n\t]', '', title or "untitled")
    name = re.sub(r'\s+', '_', name.strip())
    return name[:60] or "untitled"

def _ocr_pdf(pdf_path: Path) -> tuple[str, str]:
    """返回 (文本, 类型='text'|'ocr'|'')"""
    # 优先直接提取文字
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        pages_text = [page.get_text("text") for page in doc]
        doc.close()
        combined = "\n".join(pages_text)
        if len(combined.strip()) > 100:
            return combined, "text"
    except Exception as e:
        logging.warning(f'[convert_pdf_md] L36 {e}')

    # 图片型 PDF → PaddleOCR
    try:
        import fitz, tempfile, os
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        doc = fitz.open(str(pdf_path))
        lines = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp = f.name
            pix.save(tmp)
            result = ocr.ocr(tmp)
            os.unlink(tmp)
            if result:
                for item in result:
                    # PaddleOCR v3: OCRResult with rec_texts list
                    texts = item.get("rec_texts") if hasattr(item, "get") else None
                    if texts:
                        lines.extend(texts)
                    elif isinstance(item, list):
                        # v2 fallback: [[bbox, [text, score]], ...]
                        for line in item:
                            if line and len(line) > 1:
                                lines.append(line[1][0])
        doc.close()
        return "\n".join(lines), "ocr"
    except Exception as e:
        print(f"  OCR失败: {e}", file=sys.stderr)
        return "", ""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="最多处理N条（0=全部）")
    parser.add_argument("--text-only", action="store_true", help="只处理文字型PDF（跳过图片型）")
    args = parser.parse_args()

    MD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, project_name, pdf_path, page_path, publish_date
        FROM notices
        WHERE pdf_path IS NOT NULL AND page_path IS NULL
        ORDER BY publish_date DESC
    """).fetchall()

    if args.limit:
        rows = rows[:args.limit]

    total = len(rows)
    print(f"待转换: {total} 条")

    ok = skip = fail = 0
    for i, r in enumerate(rows, 1):
        pdf_path = Path(r["pdf_path"])
        if not pdf_path.exists():
            skip += 1
            continue

        project_name = r["project_name"] or r["id"]
        base = _safe_name(project_name)
        md_path = MD_DIR / f"{base}.md"
        # 去重
        if md_path.exists():
            suffix = abs(hash(r["id"])) % 9999 + 1
            md_path = MD_DIR / f"{base}_{suffix:04d}.md"

        print(f"[{i}/{total}] {project_name[:45]}", end=" ", flush=True)
        text, kind = _ocr_pdf(pdf_path)
        if args.text_only and kind == "ocr":
            print("→ [图片型，跳过]")
            skip += 1
            continue
        if not text or len(text.strip()) < 30:
            print("→ 空")
            fail += 1
            continue

        md_path.write_text(f"# {project_name}\n\n{text}", encoding="utf-8")
        conn.execute("UPDATE notices SET page_path=? WHERE id=?", (str(md_path), r["id"]))
        conn.commit()
        print(f"→ [{kind}] {md_path.name}  ({len(text)}字)")
        ok += 1

    conn.close()
    print(f"\n完成: 转换={ok}  跳过={skip}  失败={fail}")

if __name__ == "__main__":
    main()

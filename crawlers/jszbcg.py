#!/usr/bin/env python3
"""
江苏招标采购服务平台采集器（Pro 版）
API: GET https://api.jszbtb.com/DataGatewayApi/PublishBulletins
覆盖: bulletinType 1=招标 2=中标候选人公示 3=成交/中标 4=终止 6=不招标公示
全盐城市: regionCode=3209（已是全域，无需区域过滤）
全列入库: 23列全部进 raw_json，核心字段同步映射到标准列
"""
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests

sys.path.insert(0, os.path.dirname(__file__))
from base import BaseCrawler, make_id

logger = logging.getLogger(__name__)

# PaddleOCR singleton — 避免每次 _pdf_to_md 调用都重新初始化5个模型（会慢10~20s/条）
_OCR_INSTANCE = None

def _get_ocr():
    global _OCR_INSTANCE
    if _OCR_INSTANCE is None:
        from paddleocr import PaddleOCR
        _OCR_INSTANCE = PaddleOCR(use_angle_cls=True, lang="ch")
    return _OCR_INSTANCE

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

API_BASE   = "https://api.jszbtb.com/DataGatewayApi/PublishBulletins"
DETAIL_API = "https://api.jszbtb.com/DataGatewayApi/BulletinDetail/{bid_id}"
SITE_URL   = "https://www.jszbcg.com"
PDF_DIR    = Path(__file__).parent.parent / "data" / "pdfs" / "jszbcg"
MD_DIR     = Path(__file__).parent.parent / "data" / "pages" / "jszbcg"

# bulletinType → notice_type 映射
BULLETIN_TYPE_MAP = {
    1: ("tender",    "招标公告"),
    2: ("award",     "中标候选人公示"),
    3: ("award",     "中标结果公告"),
    4: ("other",     "终止公告"),
    6: ("other",     "不招标理由公示"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": SITE_URL + "/",
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate",
}


class JSZbcgCrawlerPro(BaseCrawler):
    SITE_KEY  = "jszbcg"
    SITE_NAME = "江苏招标采购服务平台"

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        # 找出对应的 bulletinType 值列表
        bt_list = [bt for bt, (nt, _) in BULLETIN_TYPE_MAP.items() if nt == notice_type]
        if not bt_list:
            return {"total": 0, "new": 0}

        total = new = 0
        for bt in bt_list:
            r = self._crawl_bulletin_type(bt, start_date, end_date)
            total += r["total"]
            new   += r["new"]
        return {"total": total, "new": new}

    def _crawl_bulletin_type(self, bt: int, start_date: str, end_date: str) -> Dict:
        notice_type, type_label = BULLETIN_TYPE_MAP[bt]
        logger.info(f"  [{self.SITE_NAME}] bulletinType={bt} ({type_label}) 开始采集 {start_date}~{end_date}")

        total = new = 0
        page = 1
        page_size = 100

        while True:
            data = self._fetch_page(bt, page, page_size, start_date, end_date)
            if data is None:
                logger.warning(f"    页{page}: 请求失败，停止")
                break

            records = data.get("data") or []
            if not records:
                break

            logger.debug(f"    页{page}: {len(records)} 条")
            for raw in records:
                record = self._map_record(raw, notice_type, type_label)
                if record:
                    is_new = self.save(record)
                    if is_new:
                        new += 1
                        bid_id = raw.get("bulletinID", "")
                        if bid_id:
                            pdf_path = self._download_pdf(bid_id)
                            if pdf_path:
                                md_path = self._pdf_to_md(record["id"], record["project_name"], pdf_path)
                                self.db._get_conn().execute(
                                    "UPDATE notices SET pdf_path=?, page_path=? WHERE id=?",
                                    (pdf_path, md_path or None, record["id"])
                                )
                                self.db._get_conn().commit()
                    total += 1

            total_pages = data.get("totalPage", 1) or 1
            if page >= total_pages:
                break
            page += 1
            time.sleep(0.5)

        logger.info(f"  [{self.SITE_NAME}] bulletinType={bt}: 总计{total}条 新增{new}条")
        return {"total": total, "new": new}

    def _fetch_page(
        self, bt: int, page: int, page_size: int, start_date: str, end_date: str
    ) -> Optional[Dict]:
        params = {
            "bulletinType":  bt,
            "regionCode":    "3209",
            "startTime":     f"{start_date} 00:00:00" if start_date else "",
            "endTime":       f"{end_date} 23:59:59"   if end_date   else "",
            "keyword":       "",
            "currentPage":   page,
            "pageSize":      page_size,
            "source":        "zbcg",
        }
        # 不传日期会 400
        if not start_date or not end_date:
            _end = datetime.now()
            _start = _end - timedelta(days=30)
            params["startTime"] = _start.strftime("%Y-%m-%d 00:00:00")
            params["endTime"]   = _end.strftime("%Y-%m-%d 23:59:59")

        try:
            resp = requests.get(API_BASE, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("success"):
                    return body.get("data") or {}
                logger.warning(f"    API success=false: {body.get('message','')}")
            else:
                logger.warning(f"    HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"    请求异常: {e}")
        return None

    def _download_pdf(self, bid_id: str) -> str:
        """调 Detail API 取 signPdfUrl，下载 PDF 到本地。返回本地路径，失败返回空字符串。"""
        try:
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            pdf_file = PDF_DIR / f"{bid_id}.pdf"
            if pdf_file.exists() and pdf_file.stat().st_size > 1000:
                return str(pdf_file)
            r = requests.get(DETAIL_API.format(bid_id=bid_id), headers=HEADERS, timeout=10)
            pdf_url = (r.json().get("data") or {}).get("signPdfUrl", "")
            if not pdf_url:
                return ""
            pr = requests.get(pdf_url, headers=HEADERS, timeout=30)
            if len(pr.content) < 1000:
                return ""
            pdf_file.write_bytes(pr.content)
            return str(pdf_file)
        except Exception:
            return ""

    def _pdf_to_md(self, record_id: str, project_name: str, pdf_path: str) -> str:
        """将 PDF 转成 MD 文件，按项目名命名存入 MD_DIR。返回 MD 路径，失败返回空字符串。"""
        import re as _re
        MD_DIR.mkdir(parents=True, exist_ok=True)

        def _safe(title: str) -> str:
            name = _re.sub(r'[\\/*?:"<>|\r\n\t]', '', title or "untitled")
            name = _re.sub(r'\s+', '_', name.strip())
            return name[:60] or "untitled"

        base = _safe(project_name)
        md_path = MD_DIR / f"{base}.md"
        if md_path.exists():
            suffix = abs(hash(record_id)) % 9999 + 1
            md_path = MD_DIR / f"{base}_{suffix:04d}.md"

        text = ""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            text = "\n".join(page.get_text("text") for page in doc)
            doc.close()
        except Exception as e:
            logger.warning(f'[pdf_text_fitz_warning] L197 {e}')

        if len(text.strip()) < 100:
            # 图片型 PDF → PaddleOCR（singleton，避免每次重新加载5个模型）
            try:
                import fitz, tempfile, os as _os
                ocr = _get_ocr()
                doc = fitz.open(pdf_path)
                lines = []
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                        tmp = f.name
                    pix.save(tmp)
                    result = ocr.ocr(tmp)
                    _os.unlink(tmp)
                    if result:
                        for item in result:
                            texts = item.get("rec_texts") if hasattr(item, "get") else None
                            if texts:
                                lines.extend(texts)
                            elif isinstance(item, list):
                                for line in item:
                                    if line and len(line) > 1:
                                        lines.append(line[1][0])
                doc.close()
                text = "\n".join(lines)
            except Exception as e:
                logger.warning(f"  OCR失败 {project_name}: {e}")
                return ""

        if len(text.strip()) < 30:
            return ""

        md_path.write_text(f"# {project_name}\n\n{text}", encoding="utf-8")
        return str(md_path)

    def _map_record(self, raw: Dict, notice_type: str, type_label: str) -> Optional[Dict]:
        """将 API 原始 23 列映射到标准 schema + 保留 raw_json。"""
        project_name = raw.get("bulletinName", "")
        publish_date = (raw.get("noticeSendTime") or "")[:10]

        if not project_name or not publish_date:
            return None

        # 地区处理：全域入库，不过滤
        region = raw.get("regionName", "") or ""
        district_code = raw.get("regionCode", "") or ""

        record_id = make_id(project_name, publish_date, self.SITE_NAME)
        bulletin_id = raw.get("bulletinID", "")

        return {
            "id":            record_id,
            "site":          self.SITE_KEY,
            "notice_type":   notice_type,
            "source_url":    SITE_URL,
            "detail_url":    f"{SITE_URL}/#/bulletinDetails/招标/采购公告/{bulletin_id}?bulletinType={raw.get('bulletinType','')}",
            "publish_date":  publish_date,
            "project_name":  project_name,
            "budget":        None,           # jszbcg API 不返预算金额，待详情页补全
            "budget_text":   None,
            "budget_unit":   None,
            "purchaser_raw": raw.get("projectCompany", ""),
            "open_date":     raw.get("openBidTime", "") or None,
            "deadline":      None,           # 待详情页补全
            "expected_list": None,
            "winner":        None,           # award 类待详情页补全
            "winning_amount": None,
            "region":        region,
            "district_code": district_code,
            "raw_json":      __import__("json").dumps(raw, ensure_ascii=False),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    crawler = JSZbcgCrawlerPro()
    start = "2026-06-01"
    end   = datetime.now().strftime("%Y-%m-%d")
    result = crawler.crawl_all(start, end)
    print(f"\n=== {crawler.SITE_NAME} 采集完成 ===")
    print(f"总计: {result['total']} 条，新增: {result['new']} 条")
    print(f"分类: {result['by_type']}")
    print(f"DB 统计: {crawler.db.count_by_type()}")

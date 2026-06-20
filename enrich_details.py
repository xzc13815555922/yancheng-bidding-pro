#!/usr/bin/env python3
"""
详情页补全 — Pro 版
对 notices.detail_fetched=0 的记录，补全：
  purchaser      发包/采购单位
  budget         预算金额（元）
  open_date      开标时间（tender）
  deadline       报名截止时间（tender）
  expected_list  预计挂网时间（intention）
  winner         中标单位（award）
  winning_amount 中标金额（award）

策略：
  1. jszbcg  → 从 raw_json 字段直接解（无 HTTP）
  2. sufu    → 从 raw_json / 已有字段回写（无 HTTP）
  3. HTML 类 → requests 抓详情页 + 正则解析
  4. yancheng_gov → requests 试，403 则标记 detail_fetched=2（需 Playwright，后续单独处理）
"""
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

sys.path.insert(0, str(Path(__file__).parent / "crawlers"))
from base import SiteDB, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 解析关键字
# ─────────────────────────────────────────────
PURCHASER_KEYWORDS = [
    "采购人", "采购单位", "发包单位", "发包方", "业主单位",
    "建设单位", "项目单位", "招标人", "招标单位", "委托单位",
]
BUDGET_KEYWORDS = [
    "项目预算", "采购预算", "控制价", "最高限价",
    "总投资", "投资额", "预算金额", "总预算",
    "项目规模", "服务费", "监理费", "工程造价", "项目造价",
    "合同估算价", "合同预估金额", "合同预计金额", "合同预计总金额",
    "估算价", "估算总投资",
]
BUDGET_EXCLUDE = ["保证金", "履约金", "押金", "违约金"]
OPEN_DATE_KEYWORDS  = ["开标时间", "开标日期"]
DEADLINE_KEYWORDS   = ["报名截止", "投标截止", "截标时间", "递交截止", "报名截止时间"]
EXPECTED_KEYWORDS   = ["预计挂网时间", "预计发布时间", "预计挂网日期", "预计公告时间"]
WINNER_KEYWORDS     = ["中标单位", "中标供应商", "成交供应商", "中标人",
                       "中标候选人第一名", "中标候选人", "中标侯选人"]
WIN_AMOUNT_KEYWORDS = ["中标金额", "成交金额", "中标价格", "成交价格", "中标价"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# ─────────────────────────────────────────────
# 文本解析工具
# ─────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text or "").strip()


def _strip_html(html: str) -> str:
    import html as html_lib
    text = html_lib.unescape(html)
    text = text.replace('\xa0', ' ').replace('　', ' ')  # non-breaking spaces
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-zA-Z#0-9]+;', ' ', text)
    return text


# 发包单位结尾词（仅保留歧义低的多字或强语义词，排除"部/所/院/委"等高歧义单字）
_ORG_SUFFIX = (
    r'公司|集团|局|委员会|中心|学校|医院|协会|基金|银行|事务所|研究院|研究所|大学|学院'
)
_ORG_PATTERN = re.compile(_ORG_SUFFIX)


def _extract_after_keyword(text: str, keywords: list, window: int = 100) -> Optional[str]:
    """在 text 中找 keyword，要求后5字内有冒号（避免误匹配句子中的关键字），
    返回冒号后 window 字符（去空白）。"""
    t = re.sub(r'\s+', '', text)
    for kw in keywords:
        kw_stripped = re.sub(r'\s+', '', kw)
        # keyword后0-5个任意字符+冒号
        kw_pat = re.escape(kw_stripped) + r'[^：:]{0,5}[：:]'
        m = re.search(kw_pat, t)
        if not m:
            continue
        idx = m.end()  # after the colon
        return t[idx:idx + window]
    return None


def _parse_amount(raw: str) -> Tuple[Optional[float], str]:
    """从字符串中提取金额（元）和单位。"""
    if not raw:
        return None, "UNKNOWN"
    raw = raw.replace(",", "").replace("，", "")
    # 带单位的数字
    m = re.search(r'([\d.]+)\s*(亿|万元|万|元|RMB)', raw)
    if m:
        num = float(m.group(1))
        unit = m.group(2)
        if unit == "亿":
            return num * 1e8, "亿"
        if unit in ("万元", "万"):
            return num * 1e4, "元"
        return num, "元"
    # 纯数字
    m2 = re.search(r'([\d.]+)', raw)
    if m2:
        return float(m2.group(1)), "元"
    return None, "UNKNOWN"


def _parse_datetime(raw: str) -> Optional[str]:
    """尝试将各种日期格式归一化为 'YYYY-MM-DD HH:MM:SS'。"""
    if not raw:
        return None
    raw = re.sub(r'\s+', '', raw)
    patterns = [
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})[时:](\d{1,2})分?(\d{1,2})?秒?',
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})[时:](\d{1,2})',
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})时',  # H时 without minutes
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


def _parse_date_only(raw: str) -> Optional[str]:
    """解析日期为 'YYYY-MM-DD'。"""
    if not raw:
        return None
    raw = re.sub(r'\s+', '', raw)
    m = re.search(r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})', raw)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def parse_html_detail(html: str, notice_type: str) -> Dict:
    """从 HTML 详情页文本中解析所有补全字段。"""
    result: Dict = {}
    text = _clean(_strip_html(html))

    # 发包单位：关键字后40字内，从chunk头部锚定匹配
    chunk = _extract_after_keyword(text, PURCHASER_KEYWORDS, 40)
    if chunk:
        # 若chunk内部含有另一个采购人关键字，跳到该关键字之后（处理"书面提出（招标人：XXX）"型模板）
        for _inner_kw in PURCHASER_KEYWORDS:
            _kw = re.sub(r'\s+', '', _inner_kw)
            _pos = chunk.find(_kw)
            if _pos > 1:
                _after = chunk[_pos + len(_kw):]
                _after = re.sub(r'^[：:\s\xa0]+', '', _after)
                if len(_after) >= 4:
                    chunk = _after
                    break
        chunk = re.sub(r'^[^一-龥a-zA-Z0-9]+', '', chunk)
        # 若chunk内有"名称："子串，直接从该位置提取（处理"采购包1...单位名称：XXX"型）
        m_name = re.search(r'名称[：:]', chunk)
        if m_name:
            chunk = chunk[m_name.end():]
        # "信息单位名称：" 型标签前缀（fallback）
        chunk = re.sub(r'^(?:信息)?(?:单位|机构|联系|地址)?(?:名称)?\s*[：:]\s*', '', chunk)
        # 合同"甲方：" 型前缀
        chunk = re.sub(r'^[甲乙丙丁][方部]?[）)）]*\s*[：:]\s*', '', chunk)
        chunk = re.sub(r'^(?:为|是|由|自|经|向|系|即|指|该|此|因|被|对|关|有|其|名|称)\s*', '', chunk)
        m = re.match(rf'.{{2,35}}?(?:{_ORG_SUFFIX})', chunk)
        if m:
            val = m.group(0).strip()
            if 4 < len(val) < 45:
                result["purchaser"] = val

    # 预算金额（过滤保证金等）
    t_nospace = re.sub(r'\s+', '', text)
    for kw in BUDGET_KEYWORDS:
        chunk = _extract_after_keyword(text, [kw], 60)
        if not chunk:
            # fallback: keyword直接跟数字无冒号（如"最高限价28300元"）
            m_direct = re.search(re.escape(kw) + r'[^\d，。]{0,3}([\d,.]+(?:\.\d+)?)\s*(万元|亿|元)', t_nospace)
            if m_direct:
                chunk = m_direct.group(1) + m_direct.group(2)
            else:
                continue
        ctx = text[max(0, text.find(kw) - 20):text.find(kw) + 80] if kw in text else ""
        if any(ex in ctx for ex in BUDGET_EXCLUDE):
            continue
        amount, unit = _parse_amount(chunk)
        # 基础合理性过滤：金额必须有明确单位；金额范围 100元~50亿元
        has_unit = bool(re.search(r'[万元亿]', chunk))
        if amount and amount > 0 and has_unit and 100 <= amount <= 5e10:
            result["budget"] = amount
            result["budget_unit"] = unit
            result["budget_text"] = chunk[:40]
            break

    # 时间字段
    if notice_type in ("tender", "other"):
        chunk = _extract_after_keyword(text, OPEN_DATE_KEYWORDS, 40)
        if chunk:
            dt = _parse_datetime(chunk)
            if dt:
                result["open_date"] = dt
        chunk = _extract_after_keyword(text, DEADLINE_KEYWORDS, 40)
        if chunk:
            dt = _parse_datetime(chunk)
            if dt:
                result["deadline"] = dt

    if notice_type == "intention":
        chunk = _extract_after_keyword(text, EXPECTED_KEYWORDS, 40)
        if chunk:
            result["expected_list"] = _parse_date_only(chunk)

    if notice_type == "award":
        chunk = _extract_after_keyword(text, WINNER_KEYWORDS, 80)
        winner_val = None
        if chunk:
            chunk = re.sub(r'^[^一-龥a-zA-Z0-9]+', '', chunk)
            chunk = re.sub(r'^(?:为|是|由|系|该|此|因|被)\s*', '', chunk)
            # "第一名：COMPANY" prefix — strip ranking prefix
            chunk = re.sub(r'^第[一二三1-3]名[：:]', '', chunk)
            # "推荐如下:PROJECT:WINNER;" pattern — trim at ; first, then take last : segment
            if chunk.startswith('推荐如下'):
                before_semi = re.split(r'[;；]', chunk)[0]
                parts = re.split(r'[:：]', before_semi)
                chunk = parts[-1].strip()
            val = re.split(r'[,，。；;]', chunk)[0].strip()
            # Cut off at org suffix boundary (handles "公司中标价:xxx" without separator)
            m_org = re.match(rf'.{{2,40}}?(?:{_ORG_SUFFIX})', val)
            if m_org:
                val = m_org.group(0).strip()
            if 4 < len(val) < 50 and _ORG_PATTERN.search(val):
                winner_val = val
        if not winner_val:
            # 政府采购网表格格式：中标/成交金额\n1\t供应商名称...
            t_stripped = re.sub(r'\s+', '', text)
            m = re.search(
                rf'(?:中标|成交)[^一-龥]{{0,6}}金额\d+(.{{2,35}}?(?:{_ORG_SUFFIX}))',
                t_stripped
            )
            if m:
                val = m.group(1).strip()
                if 4 < len(val) < 50:
                    winner_val = val
        if not winner_val:
            # ewb/table 格式：表头含"中标单位"，值在同行数据格中
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                for table in soup.find_all('table'):
                    headers = [th.get_text(strip=True) for th in table.find_all(['th', 'td'])[:20]]
                    w_idx = next((i for i, h in enumerate(headers) if '中标单位' in h or '成交供应商' in h), None)
                    a_idx = next((i for i, h in enumerate(headers) if '中标价格' in h or '成交金额' in h or '中标金额' in h or '中标价' in h), None)
                    if w_idx is None:
                        continue
                    for tr in table.find_all('tr')[1:]:
                        cells = [td.get_text(strip=True) for td in tr.find_all(['th', 'td'])]
                        if w_idx < len(cells):
                            v = cells[w_idx]
                            if v and _ORG_PATTERN.search(v) and 4 < len(v) < 50:
                                winner_val = v
                                if a_idx and a_idx < len(cells) and 'winning_amount' not in result:
                                    amt, _ = _parse_amount(cells[a_idx])
                                    if amt and 100 <= amt <= 5e10:
                                        result['winning_amount'] = amt
                                break
                    if winner_val:
                        break
            except Exception:
                pass
        if winner_val:
            result["winner"] = winner_val
        if "winning_amount" not in result:
            chunk = _extract_after_keyword(text, WIN_AMOUNT_KEYWORDS, 200)
            if chunk:
                amount, unit = _parse_amount(chunk)
                # 单位必须紧邻数字（避免"亿"在公司名中被误认为单位）
                has_unit = bool(re.search(r'[\d,.]+\s*(?:万元|亿元|元|万)', chunk[:150]))
                if amount and amount > 0 and has_unit and 100 <= amount <= 5e10:
                    result["winning_amount"] = amount

    return result


# ─────────────────────────────────────────────
# 站点特殊处理：直接从 raw_json 提取（无 HTTP）
# ─────────────────────────────────────────────

def enrich_from_raw_json_jszbcg(raw_json: str, notice_type: str) -> Dict:
    """jszbcg: 23 列已在 raw_json，直接映射。"""
    result = {}
    try:
        d = json.loads(raw_json)
    except Exception:
        return result

    purchaser = d.get("projectCompany") or ""
    if purchaser:
        result["purchaser"] = purchaser
        result["purchaser_raw"] = purchaser

    # openBidTime 是 API 里的"发布时间/接收时间"，不是真正开标时间
    # 但作为最佳近似，tender 类用它作为 open_date
    open_bid = d.get("openBidTime") or ""
    if open_bid and notice_type == "tender":
        result["open_date"] = _parse_datetime(open_bid)

    # 成交公告（bulletinType=3）：API 里暂无中标单位和中标金额，需要 PDF 解析（暂跳过）
    return result


def enrich_from_raw_json_sufu(raw_json: str, record_row) -> Dict:
    """苏服采: 迁移时关键字段存入 raw_json，从这里读回。"""
    result = {}
    try:
        d = json.loads(raw_json)
    except Exception:
        d = {}

    budget = d.get("budget") or record_row["budget"]
    if budget and float(budget) > 0:
        result["budget"] = float(budget)
        result["budget_unit"] = d.get("budget_unit") or record_row["budget_unit"] or "元"

    deadline = d.get("deadline") or record_row["deadline"]
    if deadline:
        result["deadline"] = deadline

    open_dt = d.get("opening_time")
    if open_dt:
        result["open_date"] = open_dt

    purchaser = d.get("purchaser") or record_row["purchaser_raw"]
    if purchaser:
        result["purchaser"] = purchaser
    return result


# ─────────────────────────────────────────────
# 主采集 + 更新
# ─────────────────────────────────────────────

def update_record(db: SiteDB, record_id: str, fields: Dict, status: int):
    """更新 notices 表中补全字段。status: 1=成功 2=失败"""
    conn = db._get_conn()
    sets = []
    vals = []
    for k, v in fields.items():
        sets.append(f"{k}=?")
        vals.append(v)
    sets.append("detail_fetched=?")
    vals.append(status)
    vals.append(record_id)
    if sets:
        conn.execute(f"UPDATE notices SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()


def enrich_site(site_key: str, limit: int = 0, dry_run: bool = False):
    db = SiteDB(site_key)
    conn = db._get_conn()

    q = "SELECT id, detail_url, notice_type, raw_json, budget, budget_unit, deadline, purchaser_raw FROM notices WHERE detail_fetched=0"
    if limit:
        q += f" LIMIT {limit}"
    rows = conn.execute(q).fetchall()

    logger.info(f"[{site_key}] 待补全: {len(rows)} 条")
    ok = fail = skip = 0
    session = requests.Session()
    session.headers.update(HEADERS)

    for row in rows:
        rid       = row["id"]
        detail_url = row["detail_url"] or ""
        ntype     = row["notice_type"] or "tender"
        raw_json  = row["raw_json"] or "{}"

        # 总是从 NULL 起步，防止前一次运行的残留值
        fields: Dict = {
            "purchaser": None,
            "budget": None, "budget_unit": None, "budget_text": None,
            "open_date": None, "deadline": None,
            "expected_list": None,
            "winner": None, "winning_amount": None,
        }
        status = 1

        # ── 特殊站：从 raw_json 提取，无需 HTTP ──
        if site_key == "jszbcg":
            fields = enrich_from_raw_json_jszbcg(raw_json, ntype)

        elif site_key == "sufu":
            fields = enrich_from_raw_json_sufu(raw_json, row)

        # ── HTML 类站：HTTP 抓详情页 ──
        elif detail_url:
            try:
                resp = session.get(detail_url, timeout=15)
                if resp.status_code == 403:
                    logger.debug(f"  403: {detail_url[:60]}")
                    status = 2  # 需要 Playwright，标记跳过
                elif resp.status_code == 200:
                    enc = resp.apparent_encoding or "utf-8"
                    try:
                        html = resp.content.decode(enc, errors="replace")
                    except Exception:
                        html = resp.text
                    fields = parse_html_detail(html, ntype)
                else:
                    status = 2
            except Exception as e:
                logger.debug(f"  请求异常 {site_key} {detail_url[:60]}: {e}")
                status = 2

            time.sleep(0.5)
        else:
            status = 2  # 无 detail_url

        if not dry_run:
            update_record(db, rid, fields, status)

        if status == 1:
            ok += 1
        elif status == 2:
            fail += 1
        else:
            skip += 1

    logger.info(f"[{site_key}] 补全结果: 成功={ok} 跳过/403={fail}")
    return {"ok": ok, "fail": fail}


def enrich_all(dry_run: bool = False):
    # jszbcg 和 sufu 不需要 HTTP，先跑
    for site_key in ["jszbcg", "sufu"]:
        enrich_site(site_key, dry_run=dry_run)

    # HTML 类站
    html_sites = [
        "yueda", "chennan", "dongfang", "jscn",
        "dushi", "bigdata", "jingkai", "kaifaqu", "ycggzy",
    ]
    for site_key in html_sites:
        db_path = DATA_DIR / f"{site_key}.db"
        if not db_path.exists():
            continue
        enrich_site(site_key, dry_run=dry_run)

    # yancheng_gov：requests 会 403，直接标记为 2（Playwright 阶段处理）
    logger.info("[yancheng_gov] 详情页需要 Playwright，跳过，标记 detail_fetched=2")
    db = SiteDB("yancheng_gov")
    db._get_conn().execute("UPDATE notices SET detail_fetched=2 WHERE detail_fetched=0")
    db._get_conn().commit()


def print_stats():
    """打印各站字段填充率。"""
    print(f"\n{'网站':<18} {'总条数':>6} {'purchaser':>10} {'budget':>8} {'open_date':>10} {'deadline':>10}")
    print("-" * 70)
    for f in sorted(DATA_DIR.glob("*.db")):
        site = f.stem
        db = SiteDB(site)
        conn = db._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
        pc  = conn.execute("SELECT COUNT(*) FROM notices WHERE purchaser IS NOT NULL AND purchaser != ''").fetchone()[0]
        bu  = conn.execute("SELECT COUNT(*) FROM notices WHERE budget IS NOT NULL").fetchone()[0]
        od  = conn.execute("SELECT COUNT(*) FROM notices WHERE open_date IS NOT NULL").fetchone()[0]
        dl  = conn.execute("SELECT COUNT(*) FROM notices WHERE deadline IS NOT NULL").fetchone()[0]
        print(f"{site:<18} {total:>6} {pc:>10} {bu:>8} {od:>10} {dl:>10}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", help="只处理指定网站")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true", help="只显示字段填充率")
    args = parser.parse_args()

    if args.stats:
        print_stats()
    elif args.site:
        enrich_site(args.site, dry_run=args.dry_run)
        print_stats()
    else:
        enrich_all(dry_run=args.dry_run)
        print_stats()

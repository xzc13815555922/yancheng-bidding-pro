#!/usr/bin/env python3
"""
add_std_district.py — 给12个DB添加 std_district 列并批量分类

优先级:
  1. district_code → 精确映射
  2. region → 关键词匹配 (ycggzy "滨海县", jszbcg "江苏省/盐城市/大丰区" 路径)
  3. 站点硬编码 (jingkai/kaifaqu=经开, chennan/bigdata=盐南)
  4. purchaser → 关键词匹配
  5. project_name → 关键词匹配
  6. NULL
"""

import json
import sqlite3
from pathlib import Path

# district_code → 标准区县（只映射具体区县；泛盐城市代码不在此处）
# 泛代码（3209/320900/320971等）返回None，走后续文本匹配，最后再兜底"市级"
CODE_MAP = [
    ("320901", "亭湖"),
    ("320902", "盐都"),
    ("320903", "盐南"),  # 盐南高新区
    ("320904", "大丰"),
    ("320921", "响水"),
    ("320922", "滨海"),
    ("320923", "阜宁"),
    ("320924", "射阳"),
    ("320925", "建湖"),
    ("320941", "经开"),
    ("320981", "东台"),
    ("320992", "盐南"),
]

# 泛市级代码：归市级但只作最后兜底
CITY_LEVEL_CODES = {"3209", "320900", "320991", "320944", "320971"}

# 站点级别分类（优先级3：district_code/region 均未命中时使用）
SITE_HARDCODE = {
    "jingkai":  "经开",
    "kaifaqu":  "经开",
    "chennan":  "盐南",
    "bigdata":  "盐南",
}
# 企业主体明确但无关键词时的兜底（purchaser/project_name 均未命中才用）
SITE_FALLBACK = {
    "dushi":    "盐南",   # 都市集团主体在盐南高新区
    "jscn":     "盐南",   # 城南=盐南，世纪城南系企业在盐南高新区
    "dongfang": "经开",   # 东方集团在盐城经开区
    "yueda":    "亭湖",   # 悦达集团主基地在亭湖区（仅对盐城本地记录生效）
}

# 省外关键词：purchaser 含这些词 → 跳过 yueda 兜底（项目在盐城以外）
OUT_OF_REGION = ["山西", "保山市", "南京", "上海", "云南", "北京", "广东", "浙江", "青浦"]

# 公司精准映射（purchaser 包含关键词 → 指定区县，优先于通用关键词）
# 用于无地名但注册地址明确的企业
COMPANY_MAP = [
    ("悦达私募基金",         "经开"),
    ("悦达资本股份",         "经开"),
    ("悦达低碳科技",         "经开"),
    ("悦达起亚汽车",         "经开"),
    ("悦达专用车",           "经开"),
]

# 区县关键词列表（用于多区县检测）
DISTRICT_KW = ["亭湖", "盐都", "盐南", "大丰", "响水", "滨海", "阜宁", "射阳", "建湖", "东台", "经开"]

# 关键词匹配（顺序敏感：越具体越优先）
KEYWORDS = [
    ("亭湖",           "亭湖"),
    ("盐都",           "盐都"),
    ("盐南",           "盐南"),
    ("城南新区",        "盐南"),  # 盐城城南新区 = 盐南
    ("经济技术开发区",  "经开"),
    ("经开",           "经开"),
    ("响水",           "响水"),
    # 注意：滨海经济开发区属于滨海县，不是经开区
    ("滨海",           "滨海"),
    ("阜宁",           "阜宁"),
    ("射阳",           "射阳"),
    ("建湖",           "建湖"),
    ("大丰",           "大丰"),
    ("东台",           "东台"),
]


def from_code(code):
    """返回具体区县；泛市级代码返回 None（由调用方兜底为市级）"""
    if not code:
        return None
    c = str(code).strip()
    for prefix, district in CODE_MAP:
        if c.startswith(prefix):
            return district
    return None


def is_city_level_code(code):
    if not code:
        return False
    c = str(code).strip()
    return c in CITY_LEVEL_CODES or c == "3209"


def from_text(text):
    if not text:
        return None
    for kw, district in KEYWORDS:
        if kw in text:
            return district
    return None


def from_company(purchaser):
    """精准公司映射，优先于通用关键词"""
    if not purchaser:
        return None
    for kw, district in COMPANY_MAP:
        if kw in purchaser:
            return district
    return None


def count_district_kw(text):
    """统计文本中命中了多少个不同区县关键词（用于多区县项目检测）"""
    if not text:
        return 0
    return sum(1 for kw in DISTRICT_KW if kw in text)


def is_out_of_region(purchaser):
    """purchaser 属于省外企业（不应用 yueda 亭湖兜底）"""
    if not purchaser:
        return False
    return any(kw in purchaser for kw in OUT_OF_REGION)


DB_DIR = Path(__file__).parent / "data"
SITES = [
    "jszbcg", "yancheng_gov", "ycggzy", "sufu",
    "yueda", "dushi", "jscn", "chennan",
    "dongfang", "bigdata", "jingkai", "kaifaqu",
]

for site in SITES:
    db_path = DB_DIR / f"{site}.db"
    if not db_path.exists():
        print(f"[SKIP] {site}.db not found")
        continue

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 建列（幂等）
    cols = [r[1] for r in cur.execute("PRAGMA table_info(notices)").fetchall()]
    if "std_district" not in cols:
        cur.execute("ALTER TABLE notices ADD COLUMN std_district TEXT")

    # 重新分类（全量覆盖，方便反复调整）
    cur.execute("UPDATE notices SET std_district = NULL")

    rows = cur.execute(
        "SELECT id, district_code, region, purchaser, project_name, raw_json FROM notices"
    ).fetchall()

    hardcode = SITE_HARDCODE.get(site)
    fallback = SITE_FALLBACK.get(site)
    updates = []

    for row in rows:
        code = row["district_code"]
        raw = {}
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except Exception:
            pass

        # ── sufu 特殊处理 ──────────────────────────────────────────────
        # district_code 为空时，读 raw_json.region（API 已明确区分）
        sufu_region = None
        if site == "sufu" and not code:
            sufu_region = raw.get("region", "")

        # ── yancheng_gov col_name"(市级)"标志（仅作兜底，不作覆盖）──────
        yg_city_level = (site == "yancheng_gov" and "(市级)" in raw.get("col_name", ""))

        # 优先级流水线
        # 1. 具体 district_code（6位精确码）
        d = from_code(code)
        # 2a. sufu raw_json.region（仅 sufu 且 code 为空时）
        if not d and sufu_region:
            d = from_text(sufu_region)
        # 2b. region 字段关键词（jszbcg 路径；ycggzy 县名等）
        if not d:
            d = from_text(row["region"])
        # 3. 站点硬编码
        if not d:
            d = hardcode
        # 4a. 公司精准映射（注册地址明确、名称无区县词）
        if not d:
            d = from_company(row["purchaser"])
        # 4b. purchaser 通用关键词
        if not d:
            d = from_text(row["purchaser"])
        # 5. project_name 关键词
        if not d:
            d = from_text(row["project_name"])
        # 5.5 多区县检测：project_name 同时含≥2个区县词 → 市级
        if d and site == "jszbcg":
            pname = row["project_name"] or ""
            if count_district_kw(pname) >= 2:
                d = "市级"
        # 6. yancheng_gov "(市级)"兜底（文本已找到区县则不覆盖）
        if not d and yg_city_level:
            d = "市级"
        # 7. 站点级别兜底（企业主体区域明确的，yueda省外项目跳过）
        if not d:
            if site == "yueda" and is_out_of_region(row["purchaser"]):
                d = None  # 省外项目保持NULL
            else:
                d = fallback
        # 8. 泛市级 code 兜底
        if not d and is_city_level_code(code):
            d = "市级"
        updates.append((d, row["id"]))

    cur.executemany("UPDATE notices SET std_district = ? WHERE id = ?", updates)
    conn.commit()

    # 统计
    stats = cur.execute(
        "SELECT std_district, COUNT(*) n FROM notices GROUP BY std_district ORDER BY n DESC"
    ).fetchall()
    total = len(rows)
    filled = sum(r["n"] for r in stats if r["std_district"])
    pct = filled * 100 // total if total else 0
    detail = {(r["std_district"] or "NULL"): r["n"] for r in stats}
    print(f"[{site:<12}] {filled}/{total} ({pct}%)  {detail}")

    conn.close()

print("\n✅ Done")

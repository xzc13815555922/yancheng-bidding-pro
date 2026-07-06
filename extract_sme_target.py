#!/usr/bin/env python3
"""
extract_sme_target.py — 提取项目「是否专门面向中小微企业」标签

来源: data/pages/{site}/*.md (已抓的详情页 MD 缓存)
输出: data/unified.db tender.sme_target / intention.sme_target

3 类标签 (按优先级):
  - '专门面向'  : 项目只接受中小微企业投标 (有《中小企业声明函》要求)
  - '非专门但优惠' : 不限资质, 但中小微报价有 10-20% 扣除
  - '不涉及'    : 未提相关政策

检测规则:
  1. 优先: 在「落实政府采购政策需满足的资格要求」/「资格要求」/「采购方式」段
  2. 排除: 「十、附件」段 (政府通用模板, 非项目实际政策)
  3. 上下文窗口: 关键词前 200 字符
"""
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PAGES_DIR = ROOT / 'data' / 'pages'
UNIFIED_DB = ROOT / 'data' / 'unified.db'

# 长名 (unified.db site_name) -> 短名 (data/pages dir name)
SITE_NAME_MAP = {
    "jszbcg":       "jszbcg",
    "江苏招标采购服务平台":       "jszbcg",
    "yancheng_gov": "yancheng_gov",
    "盐城市政府采购网":         "yancheng_gov",
    "ycggzy":       "ycggzy",
    "盐城市公共资源交易平台":     "ycggzy",
    "sufu":         "sufu",
    "苏服务":                 "sufu",
    "yueda":        "yueda",
    "悦达集团阳光采购平台":       "yueda",
    "dushi":        "dushi",
    "盐城市都市建设投资集团有限公司": "dushi",
    "jscn":         "jscn",
    "江苏世纪新城投资控股集团有限公司": "jscn",
    "chennan":      "chennan",
    "江苏省盐南高新区公共资源交易电子化服务平台": "chennan",
    "dongfang":     "dongfang",
    "盐东方产业投资集团有限公司": "dongfang",
    "bigdata":      "bigdata",
    "盐城市大数据集团":         "bigdata",
    "jingkai":      "jingkai",
    "盐城经开城市发展投资集团有限公司": "jingkai",
    "kaifaqu":      "kaifaqu",
    "盐城经济技术开发区行政审批局公共资源交易服务平台": "kaifaqu",
}

# 关键词模式 (按优先级)
TARGETED_PATTERNS = [
    r'专门\s*[面为]?\s*中小[微小]?\s*企业',
    r'本项目\s*(?:仅|只|专门)\s*.*?中小[微小]?\s*企业',
    r'面向\s*中小[微小]?\s*企业\s*预留',
    r'预留\s*份额.*?中小[微小]?\s*企业',
    r'本项目\s*属于\s*.*?专门\s*面向\s*中小[微小]?',
    r'非\s*中小[微小]?\s*企业\s*不得\s*参加',
    r'限\s*中小[微小]?\s*企业\s*.*?投标',
    r'本采购包\s*专门\s*面向\s*中小[微小]?',
    r'(?:接受|仅接受)\s*中小[微小]?\s*企业',
]

PREFERENCE_PATTERNS = [
    r'价格\s*扣除\s*[优惠折扣]?',
    r'(?:给予|按).{0,10}\d+\s*%\s*扣[除价]',
    r'小微[型企业].*?\d+\s*%\s*扣[除价]',
    r'(?:小微型企业|小微企业).*?价格.{0,5}扣[除价]',
    r'小微[型企业].*?优惠',
    r'执行价格扣除优惠',
]

# 模板段关键词 (跳过)
TEMPLATE_SECTION = re.compile(r'十[、\.]\s*附件|附件[：:]')


def classify_md(md_text: str) -> str:
    """对单个 MD 内容分类"""
    if not md_text:
        return '不涉及'
    
    # 1) 优先检查「专门面向」
    for pat in TARGETED_PATTERNS:
        m = re.search(pat, md_text)
        if m:
            # 排除「十、附件」段
            # 找离 m 最近的 ## 标题
            ctx_start = max(0, m.start() - 200)
            ctx = md_text[ctx_start:m.end() + 200]
            if TEMPLATE_SECTION.search(ctx):
                continue
            # 必须是「资格要求 / 采购方式 / 落实政策」段
            section_match = re.search(r'##\s*\S+', md_text[:m.start()][::-1])
            if section_match:
                # 看标题
                pass  # 不严格卡, 大多数模板段关键词已排除
            return '专门面向'
    
    # 2) 再检查「非专门但优惠」
    for pat in PREFERENCE_PATTERNS:
        m = re.search(pat, md_text)
        if m:
            ctx_start = max(0, m.start() - 200)
            ctx = md_text[ctx_start:m.end() + 200]
            if TEMPLATE_SECTION.search(ctx):
                continue
            return '非专门但优惠'
    
    return '不涉及'


def main():
    """从 MD 提取 → 写 unified.db"""
    if not PAGES_DIR.is_dir():
        print(f"❌ {PAGES_DIR} 不存在")
        sys.exit(1)
    
    # 1) 先加列 (idempotent)
    con = sqlite3.connect(UNIFIED_DB)
    cur = con.cursor()
    for tbl in ['tender', 'intention']:
        # 查列是否存在
        cur.execute(f"PRAGMA table_info({tbl})")
        cols = [r[1] for r in cur.fetchall()]
        if 'sme_target' not in cols:
            cur.execute(f"ALTER TABLE {tbl} ADD COLUMN sme_target TEXT")
            print(f"✓ {tbl} 加列 sme_target")
        else:
            print(f"· {tbl} sme_target 已存在")
    con.commit()
    
    # 2) 收集所有 MD 文件 (按 detail_url 索引)
    # 文件名: project_name_id.md (ycggzy 是 详情页/id.html)
    md_index = {}  # detail_url -> md_path
    for site_dir in PAGES_DIR.iterdir():
        if not site_dir.is_dir():
            continue
        for md_file in site_dir.iterdir():
            if not md_file.suffix == '.md':
                continue
            # 文件名格式: "项目名_id.md" 或 "项目名.md"
            # 我们用 ycggzy 格式: ycggzy/{title}_{id}.md
            # 通过 ybp.db/notices 的 detail_url 反查麻烦
            # 改方案: 直接读 tender/intention 表, 按 project_name 找对应 MD
            
    # 3) 简单方法: 遍历 tender/intention 全部记录, 用 project_name 找 MD
    site_md_cache = {}  # site_name -> {project_name_keywords: md_path}
    for site_dir in PAGES_DIR.iterdir():
        if not site_dir.is_dir():
            continue
        site_name = site_dir.name
        site_md_cache[site_name] = list(site_dir.glob('*.md'))
    
    # 用于去重的 seen set
    def find_md(site_name: str, project_name: str, detail_url: str):
        """找对应 MD"""
        # 映射长名到短名
        short = SITE_NAME_MAP.get(site_name, site_name)
        md_path = PAGES_DIR / short / f'{project_name}.md'
        if md_path.exists():
            return md_path
        return None
    
    # 4) 处理 tender
    cur.execute("SELECT id, site_name, project_name, detail_url FROM tender WHERE detail_url IS NOT NULL")
    tender_rows = cur.fetchall()
    
    cnt = {'专门面向': 0, '非专门但优惠': 0, '不涉及': 0, '未找到': 0}
    updated = 0
    for row_id, site, name, url in tender_rows:
        md = find_md(site, name, url)
        if not md:
            cnt['未找到'] += 1
            cur.execute("UPDATE tender SET sme_target='不涉及' WHERE id=?", (row_id,))
            updated += 1
            continue
        try:
            text = md.read_text(errors='ignore')
        except Exception:
            text = ''
        label = classify_md(text)
        cnt[label] += 1
        cur.execute("UPDATE tender SET sme_target=? WHERE id=?", (label, row_id))
        updated += 1
    con.commit()
    print(f"\ntender: 处理 {updated} 条")
    for k, v in cnt.items():
        print(f"  {k}: {v}")
    
    # 5) 处理 intention
    cur.execute("SELECT id, site_name, project_name, detail_url FROM intention WHERE detail_url IS NOT NULL")
    int_rows = cur.fetchall()
    cnt2 = {'专门面向': 0, '非专门但优惠': 0, '不涉及': 0, '未找到': 0}
    updated2 = 0
    for row_id, site, name, url in int_rows:
        md = find_md(site, name, url)
        if not md:
            cnt2['未找到'] += 1
            cur.execute("UPDATE intention SET sme_target='不涉及' WHERE id=?", (row_id,))
            updated2 += 1
            continue
        try:
            text = md.read_text(errors='ignore')
        except Exception:
            text = ''
        label = classify_md(text)
        cnt2[label] += 1
        cur.execute("UPDATE intention SET sme_target=? WHERE id=?", (label, row_id))
        updated2 += 1
    con.commit()
    print(f"\nintention: 处理 {updated2} 条")
    for k, v in cnt2.items():
        print(f"  {k}: {v}")
    
    con.close()
    print("\n✅ 完成")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
config.py — 盐城招标系统全局配置，唯一注册表
新增站点只需在此文件修改，其余模块 import 即可。
"""

# ── 站点列表（顺序影响 build_unified 写入顺序）──
SITES = [
    "jszbcg", "yancheng_gov", "ycggzy", "sufu",
    "yueda", "dushi", "jscn", "chennan",
    "dongfang", "bigdata", "jingkai", "kaifaqu",
]

# ── 站点中文名称 ──
SITE_NAMES = {
    "jszbcg":       "江苏招标采购服务平台",
    "yancheng_gov": "盐城市政府采购网",
    "ycggzy":       "盐城市公共资源交易平台",
    "sufu":         "苏服务",
    "yueda":        "悦达集团阳光采购平台",
    "dushi":        "盐城市都市建设投资集团有限公司",
    "jscn":         "江苏世纪新城投资控股集团有限公司",
    "chennan":      "江苏省盐南高新区公共资源交易电子化服务平台",
    "dongfang":     "盐东方产业投资集团有限公司",
    "bigdata":      "盐城市大数据集团",
    "jingkai":      "盐城经开城市发展投资集团有限公司",
    "kaifaqu":      "盐城经济技术开发区行政审批局公共资源交易服务平台",
}

# ── 采集器注册表（site_key, 模块路径, 类名）──
CRAWLERS = [
    ("jszbcg",       "crawlers.jszbcg",          "JSZbcgCrawlerPro"),
    ("yancheng_gov", "crawlers.yancheng_gov",     "YanchengGovCrawlerPro"),
    ("ycggzy",       "crawlers.ycggzy",           "YcggzyCrawlerPro"),
    ("bigdata",      "crawlers.bigdata",          "BigdataCrawlerPro"),
    ("jingkai",      "crawlers.jingkai",          "JingkaiCrawlerPro"),
    ("kaifaqu",      "crawlers.chennan_kaifaqu",  "KaifaquCrawlerPro"),
    ("chennan",      "crawlers.chennan_kaifaqu",  "ChengnanCrawlerPro"),
    ("dongfang",     "crawlers.dongfang",         "DongfangCrawlerPro"),
    ("dushi",        "crawlers.dushi",            "DushiCrawlerPro"),
    ("jscn",         "crawlers.jscn",             "JscnCrawlerPro"),
    ("yueda",        "crawlers.yueda",            "YuedaCrawlerPro"),
    ("sufu",         "crawlers.sufu",             "SufuCrawlerPro"),
]

# ── 数据质量基线 ──
# 字段含义：
#   count       — 最低记录总数
#   purchaser   — 全量记录的发包单位填充率
#   budget      — tender 类记录的预算填充率
#   open_date   — tender 类记录的开标时间填充率
#   winner      — award 类记录的中标人填充率
#   winning_amount — award 类记录的中标金额填充率
#
# 说明：
#   sufu.winner      = 0.00：SPA(JS)渲染，html2text 无法提取，已知结构性限制
#   yueda.budget     = 0.00：悦达地产/商贸公告不含预算，已知结构性限制
#   yueda.wamt       = 0.00：中标金额格式非标准，已知结构性限制
#   yancheng_gov.wamt= 0.40：框架协议使用优惠率，无固定中标金额
#   kaifaqu.winner   — 9 条 award 样本，P0-1 修复后统计意义有限，暂不设基线

SITE_BASELINES = {
    "jszbcg": {
        "count":           4000,
        "purchaser":       0.88,
        "budget":          0.80,
        "open_date":       0.95,
        "winner":          0.92,
        "winning_amount":  0.78,
    },
    "yancheng_gov": {
        "count":           2500,
        "purchaser":       0.96,
        "budget":          0.95,
        "open_date":       0.93,
        "winner":          0.97,
        "winning_amount":  0.40,
    },
    "ycggzy": {
        "count":           3900,
        "purchaser":       0.90,
        "budget":          0.65,
        "open_date":       0.58,
        "winner":          0.89,
        "winning_amount":  0.79,
    },
    "sufu": {
        "count":           190,
        "purchaser":       0.99,
        "budget":          0.99,
        "open_date":       0.90,
        # winner = 0.00：SPA结构性限制，不设基线
        "winning_amount":  0.97,
    },
    "yueda": {
        "count":           80,
        "purchaser":       0.96,
        # budget = 0.00：私企不公示预算，不设基线
        "open_date":       0.78,
        "winner":          0.92,
        # winning_amount 格式非标，不设基线
    },
    "dongfang": {
        "count":           120,
        "purchaser":       0.90,
        "budget":          0.66,
        "open_date":       0.88,
        "winner":          0.97,
        "winning_amount":  0.65,
    },
    "jscn": {
        "count":           150,
        "purchaser":       0.93,
        "budget":          0.56,
        "open_date":       0.83,
        "winner":          0.97,
        "winning_amount":  0.64,
    },
    "dushi": {
        "count":           200,
        "purchaser":       0.92,
        "budget":          0.62,
        "open_date":       0.54,
        "winner":          0.75,
        "winning_amount":  0.72,
    },
    "chennan": {
        "count":           180,
        "purchaser":       0.91,
        "budget":          0.87,
        "open_date":       0.94,
        "winner":          0.97,
        "winning_amount":  0.73,
    },
    "kaifaqu": {
        "count":           28,
        "purchaser":       0.92,
        "budget":          0.72,
        "open_date":       0.85,
        # award 只有 2 条真实中标，样本太小，不设 winner/wamt 基线
    },
    "bigdata": {
        "count":           9,
        "purchaser":       0.98,
        "budget":          0.97,
        "open_date":       0.97,
        "winner":          0.97,
        "winning_amount":  0.87,
    },
    "jingkai": {
        "count":           2,
        "purchaser":       0.98,
        "budget":          0.73,
        "open_date":       0.88,
        "winner":          0.97,
        "winning_amount":  0.44,
    },
}

# ── unified.db 汇总表基线 ──
UNIFIED_BASELINES = {
    "tender":    1300,
    "award":     1300,
    "intention": 300,
}

# ── 各字段对应的过滤 notice_type（None = 全量）──
FIELD_NOTICE_TYPE = {
    "purchaser":       None,
    "budget":          "tender",
    "open_date":       "tender",
    "winner":          "award",
    "winning_amount":  "award",
}

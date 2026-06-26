#!/usr/bin/env python3
"""
enrich_amendment_opendate.py — 更正公告 open_date 联动更新

从 other 类型的更正公告页面中提取新开标时间，匹配并更新对应 tender 记录的 open_date。

用法:
  python3 enrich_amendment_opendate.py            # dry-run（默认，仅打印，不写库）
  python3 enrich_amendment_opendate.py --write    # 执行更新
  python3 enrich_amendment_opendate.py --site yancheng_gov  # 仅处理指定站点
"""
import argparse
import re
import sqlite3
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

SITES = ["yancheng_gov", "jszbcg", "ycggzy", "chennan", "dushi", "jscn"]

# 新开标时间提取：找"现更正为/变更为/延至..."后紧跟的日期
NEW_DATE_PAT = re.compile(
    r"(?:现更正为|变更为|更改为|延至|延期至|修改为|调整为)"
    r"[^，。\n]{0,15}?(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2})"
)

# 更正/变更/延期公告后缀 → 剥离还原原项目名
AMEND_WORDS = re.compile(
    r"[（(]?(?:更正|变更|延期|补充|澄清|修正)[^（\n]{0,5}(?:公告|公示)[^（\n]{0,10}$"
)

# jszbcg 格式：【更正公告】xxx、【变更公告】xxx 等前缀
AMEND_PREFIX = re.compile(
    r"^(?:\s*【[^】]*(?:更正|变更|延期|补充|澄清|答疑|修正)[^】]*】\s*)+"
)


def strip_amendment_suffix(name: str) -> str:
    n = name.strip()
    # 先剥前缀（jszbcg 【更正公告】xxx 格式）
    n = AMEND_PREFIX.sub("", n).strip()
    # 再剥后缀（最多 4 次，处理叠加后缀）
    for _ in range(4):
        m = AMEND_WORDS.search(n)
        if m:
            n = n[: m.start()].strip()
        else:
            break
    return n


def parse_cn_date(s: str) -> str:
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", s)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    return s[:10]


def normalize_date(od: str) -> str:
    """把带时分的 open_date 截到 YYYY-MM-DD。"""
    return (od or "")[:10]


def process_site(site: str, write: bool) -> dict:
    db_path = DATA_DIR / f"{site}.db"
    if not db_path.exists():
        return {}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    amendments = conn.execute("""
        SELECT id, project_name, page_path, publish_date
        FROM notices WHERE notice_type='other'
        AND (project_name LIKE '%更正%' OR project_name LIKE '%延期%'
             OR project_name LIKE '%变更%' OR project_name LIKE '%补充%')
        AND page_path IS NOT NULL AND page_path != ''
    """).fetchall()

    tenders = conn.execute("""
        SELECT id, project_name, open_date, publish_date
        FROM notices WHERE notice_type IN ('tender', 'requirement')
    """).fetchall()

    results = {"update": [], "skip": [], "multi": [], "no_match": [], "no_date": []}
    updates_to_apply = []  # [(new_od, tender_id)]

    for amend in amendments:
        name = amend["project_name"] or ""
        pp = amend["page_path"]
        pub = amend["publish_date"] or ""

        p = Path(pp)
        if not p.exists():
            continue

        content = p.read_text(errors="ignore")
        m = NEW_DATE_PAT.search(content)
        if not m:
            results["no_date"].append(name)
            continue

        new_date = parse_cn_date(m.group(1))

        # 日期合理性：更正后的日期应在 publish_date ± 6 个月
        try:
            pub_dt = datetime.strptime(pub[:10], "%Y-%m-%d")
            new_dt = datetime.strptime(new_date, "%Y-%m-%d")
            if abs((new_dt - pub_dt).days) > 180:
                results["no_date"].append(f"{name} [日期超范围: {new_date}]")
                continue
        except Exception:
            continue

        stripped = strip_amendment_suffix(name)
        if stripped == name:
            results["no_match"].append(f"{name} [suffix剥离失败]")
            continue

        # 匹配 tender：stripped 是 tname 的子串，或 tname 是 stripped 的子串
        candidates = []
        for t in tenders:
            tname = t["project_name"] or ""
            if len(stripped) < 10 or len(tname) < 10:
                continue
            if tname == stripped or stripped in tname or tname in stripped:
                # tender 必须在 amendment 之前发布
                if (t["publish_date"] or "") <= pub:
                    candidates.append(t)

        if not candidates:
            results["no_match"].append(stripped)
            continue

        if len(candidates) > 1:
            # 尝试用 stripped 中的批次数字消歧（四次/三次/二次/第N次 等）
            round_m = re.search(r"[（(]([一二三四五六七八九十\d]+)[）)]$", stripped)
            if round_m:
                suffix = round_m.group(1)
                narrowed = [t for t in candidates
                            if re.search(r"[（(]" + suffix + r"[）)]", t["project_name"] or "")]
                if len(narrowed) == 1:
                    candidates = narrowed
            # 还是多个 → 取最新发布的
            if len(candidates) > 1:
                candidates_sorted = sorted(
                    candidates, key=lambda t: t["publish_date"] or "", reverse=True
                )
                results["multi"].append({
                    "amend": name, "stripped": stripped,
                    "new_date": new_date,
                    "candidates": [(t["id"], t["project_name"][:40]) for t in candidates],
                    "chosen": candidates_sorted[0]["id"],
                })
                # 保守策略：多重候选不自动写入
                continue

        tender = candidates[0]
        current_od = normalize_date(tender["open_date"])

        if current_od == new_date:
            results["skip"].append({"amend": name, "reason": "same", "new_date": new_date})
            continue

        results["update"].append({
            "amend": name,
            "tender_id": tender["id"],
            "tender_name": tender["project_name"],
            "current_od": tender["open_date"],
            "new_od": new_date,
        })
        updates_to_apply.append((new_date, tender["id"]))

    # 执行写入
    if write and updates_to_apply:
        conn.executemany(
            "UPDATE notices SET open_date=? WHERE id=?", updates_to_apply
        )
        conn.commit()

    conn.close()
    return results


def print_results(site: str, results: dict, write: bool):
    print(f"\n[{site}]")
    for r in results.get("update", []):
        flag = "✅ WRITE" if write else "⬜ UPDATE"
        direction = "→"
        print(f"  {flag}  {r['amend'][:55]}")
        print(f"         open_date: {r['current_od']} {direction} {r['new_od']}")

    for r in results.get("multi", []):
        print(f"  ⚠️  MULTI  {r['amend'][:55]}")
        print(f"         新日期: {r['new_date']}, 候选:")
        for tid, tname in r["candidates"]:
            print(f"           - {tname}")

    for name in results.get("no_match", []):
        print(f"  ⚪ NOMATCH {name[:55]}")


def main():
    parser = argparse.ArgumentParser(description="更正公告 open_date 联动更新")
    parser.add_argument("--write", action="store_true", help="实际执行更新（默认 dry-run）")
    parser.add_argument("--site", default="", help="限定站点 key（如 yancheng_gov）")
    parser.add_argument("--quiet", action="store_true", help="只打印摘要，不打印详情")
    args = parser.parse_args()

    sites = [args.site] if args.site else SITES
    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"=== 更正公告 open_date 联动 [{mode}] ===")

    grand = {"update": 0, "skip": 0, "multi": 0, "no_match": 0}
    for site in sites:
        results = process_site(site, write=args.write)
        if not results:
            continue
        if not args.quiet:
            print_results(site, results, args.write)
        grand["update"] += len(results.get("update", []))
        grand["skip"]   += len(results.get("skip", []))
        grand["multi"]  += len(results.get("multi", []))
        grand["no_match"] += len(results.get("no_match", []))

    print(f"\n=== 汇总 ===")
    print(f"  {'写入' if args.write else '待更新'}: {grand['update']}")
    print(f"  跳过(同值): {grand['skip']}")
    print(f"  多重候选(需人工): {grand['multi']}")
    print(f"  未匹配: {grand['no_match']}")
    if not args.write:
        print(f"\n  添加 --write 执行实际更新")


if __name__ == "__main__":
    main()

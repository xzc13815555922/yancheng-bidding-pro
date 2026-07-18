#!/usr/bin/env python3
"""
T-1: AST 扫描器 — 防 except:pass 回归（P0-3 修复后底线）
================================================================
扫描 crawlers/ 与项目根的 .py 文件，识别"盲洞"：
    except ... :
        pass                         # 真黑洞
        logger.warning(...)          # logging-then-swallow 黑洞
        warnings.warn(...)
        print(...) / print(msg)

黑洞会"吞掉异常让流程静默继续"，是 v2.7 实战最怕的回归形态。

策略：
- 当前历史 56 处黑洞逐条列在 ALLOWED_DROPS（2026-07-07 P0-P3 修复期沉淀）。
- 新引入任何 (file, line) 不在 allowlist → 立刻 fail。
- allowlist 改动必须人工 PR 评审，不允许 regenerate。

复跑：pytest tests/test_black_holes.py -v
"""
import ast
import pathlib

import pytest

# P0-1 (2026-07-11): 不再硬编码绝对路径,改从本测试文件位置推导项目根
# 别人 git clone 到任意位置都能扫到真代码
PROJ = pathlib.Path(__file__).resolve().parents[1]

SKIP_KEYWORDS = ("test_", "backup", "__pycache__", ".git", "/output/", "/audit/")

# 允许的"吞掉异常"函数（仅作 logging 用途的，不算黑洞）
ALLOWED_LOG_FUNCS = (
    "logger.warning", "logger.info", "logger.debug", "logger.error",
    "logging.warning", "logging.info", "logging.debug", "logging.error",
    "log.warning", "log.info", "log.debug",
    "warnings.warn", "print",
)


def _is_swallow(body: list) -> bool:
    """判定 except 块体是否只 '吞掉'：body 空 / 全是 logging/print/pass。

    触发条件都必须是「silently swallow」：
    - 空 body（什么都不做）→ 黑洞
    - 只有 Pass → 黑洞
    - 只有 logging/warn/print → 黑洞（不 raise 也不交接）

    例外（不算黑洞）：
    - body 含 Continue / Return（有意义控制流）
    - body 含 Raise / Raise X（重新抛出）
    - body 含业务处理（赋值、if else 等）
    """
    if not body:
        return True
    top = body[:3]  # 只看首 3 条
    for s in top:
        if isinstance(s, ast.Pass):
            continue
        if isinstance(s, (ast.Continue, ast.Return, ast.Raise)):
            return False  # 有意义流转
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
            tgt = ast.unparse(s.value.func)
            if any(tgt == af or tgt.endswith("." + af.split(".")[-1]) for af in ALLOWED_LOG_FUNCS):
                continue
            return False
        return False
    return True


def find_swallow_handlers(filepath: pathlib.Path) -> list:
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    holes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if _is_swallow(node.body):
                holes.append((filepath.name, node.lineno, str(filepath)))
    return holes


def scan_dir(subdir: str) -> list:
    results = []
    base = PROJ if subdir == "." else PROJ / subdir
    for fp in base.rglob("*.py"):
        s = str(fp)
        if any(k in s for k in SKIP_KEYWORDS):
            continue
        results.extend(find_swallow_handlers(fp))
    return results


# ────────────────────────────────────────────────────────────────
# 当前历史黑洞 — 2026-07-07 P0-P3 修复期沉淀（不许删，下次引入必须 fail）
# 格式: (basename, line_no)
# ────────────────────────────────────────────────────────────────
ALLOWED_DROPS = {
    ("convert_jszbcg_pdfs_to_md.py", 36),
    ("reenrich_ycggzy.py", 48),
    ("download_site_pages.py", 82),
    ("cleanup_orphan_dbs.py", 44),
    ("build_unified.py", 180),
    ("build_unified.py", 196),
    ("build_unified.py", 230),
    ("extract_sme_target.py", 115),
    ("add_std_district.py", 187),
    ("enrich_jszbcg_ocr.py", 325),
    ("enrich_jszbcg_ocr.py", 186),
    ("enrich_jszbcg_ocr.py", 155),
    ("enrich_jszbcg_ocr.py", 286),
    ("enrich_details.py", 654),
    ("enrich_details.py", 501),
    ("enrich_details.py", 757),
    ("enrich_details.py", 804),
    ("enrich_yancheng_gov.py", 276),
    ("run_collection.py", 60),
    ("run_collection.py", 106),
    ("run_collection.py", 95),
    ("run_collection.py", 117),
    ("export_excel.py", 202),
    ("yancheng_gov.py", 233),
    ("yancheng_gov.py", 215),
    ("jscn.py", 83),
    ("chennan_kaifaqu.py", 103),
    ("dushi.py", 115),
    ("dongfang.py", 100),
    ("jingkai.py", 93),
    ("yueda.py", 110),
    ("bigdata.py", 91),
    ("jszbcg.py", 152),
    ("jszbcg.py", 197),
    ("ycggzy.py", 137),
    ("ycggzy.py", 141),
    ("ycggzy.py", 292),
    ("ycggzy.py", 451),
    ("ycggzy.py", 588),
    ("tyc_login.py", 79),
    ("tyc_login.py", 223),
    ("tyc_login.py", 228),
    ("tyc_crawler.py", 285),
    ("tyc_crawler.py", 299),
    ("tyc_crawler.py", 383),
    ("tyc_crawler.py", 405),
    ("tyc_crawler.py", 410),
    ("tyc_crawler.py", 421),
    ("tyc_crawler.py", 441),
    ("tyc_crawler.py", 514),
    ("tyc_crawler.py", 601),
    ("tyc_crawler.py", 609),
    ("tyc_crawler.py", 614),
    ("tyc_crawler.py", 619),
    ("tyc_crawler.py", 623),
    ("base.py", 110),
    ("base.py", 293),
    ("base.py", 295),
    # ── 2026-07-18 数据治理 P0-采-1 + P1-采-1 新增黑洞 ──
    # 告警机制本身不能成为故障源（采集失败告警 / JSONL 镜像）
    ("run_collection.py", 177),
    ("run_collection.py", 221),
}


def _filter_allowed(holes):
    """分离 (历史允许) 与 (新增黑洞)

    P0-2 (2026-07-11) 修复:
      之前按 line 单独判重 `seen.add(line)`, 跨文件同 line 的黑洞会被
      静默去重 → 漏报。
      改为按 (name, line) 复合键判重。
    """
    existing, new = [], []
    seen = set()
    for name, line, full in holes:
        key = (name, line)
        if key in seen:  # 防重复扫描导致重复报错 (现在按复合键)
            continue
        seen.add(key)
        if key in ALLOWED_DROPS:
            existing.append(key)
        else:
            new.append((name, line, full))
    return existing, new


@pytest.mark.parametrize("subdir", ["crawlers", "."])
def test_no_new_swallow_handlers(subdir):
    """核心路径无新盲洞（历史 56 处保留在 ALLOWED_DROPS）"""
    holes = scan_dir(subdir)
    existing, new = _filter_allowed(holes)

    msg_lines = [f"⚠ 新增 except swallow 黑洞 ({len(new)} 处) in {subdir}/:"]
    for name, line, full in new:
        msg_lines.append(f"   - {name}:{line}")
    msg_lines.append("")
    msg_lines.append(f"修复方式二选一：")
    msg_lines.append(f"  1. 真正处理异常：retire raise / fallback 处理完整")
    msg_lines.append(f"  2. 加 allowlist：编辑 ALLOWED_DROPS 并 PR 评审")

    assert not new, "\n".join(msg_lines)


def test_allowlist_matches_current_count():
    """白名单条目数与当前实际黑洞数对齐（防止有人手动改文件没刷新 allowlist）"""
    all_holes = []
    all_holes.extend(scan_dir("crawlers"))
    all_holes.extend(scan_dir("."))
    existing, new = _filter_allowed(all_holes)

    assert not new, (
        f"新增 {len(new)} 个黑洞，且未加入 allowlist：\n"
        + "\n".join(f"  {n}:{l}" for n, l, _ in new)
    )

    # 检查 allowlist 中"已不存在的"条目（文件改了但 allowlist 残留）
    cur_set = {(n, l) for n, l, _ in all_holes}
    stale = ALLOWED_DROPS - cur_set
    assert not stale, (
        f"allowlist 残留 {len(stale)} 个旧条目（文件已修改），请清理：\n"
        + "\n".join(f"  ({n!r}, {l})" for n, l in sorted(stale))
    )


def test_filter_allowed_dedup_by_composite_key():
    """P0-2 回归: _filter_allowed 必须按 (name, line) 复合键去重,
    跨文件同 line 黑洞不得静默漏报。
    """
    # 场景: 同一个 line=42 在 a.py 和 b.py 都出现黑洞
    # - a.py:42 在 ALLOWED_DROPS 中 → 视为历史允许
    # - b.py:42 不在 ALLOWED_DROPS → 应被报为新增黑洞
    # 如果用 line-only 去重, b.py:42 会被 seen 拦截掉 → 漏报
    holes = [
        ("a.py", 42, "/fake/a.py"),
        ("b.py", 42, "/fake/b.py"),
    ]
    # 把 a.py:42 临时加进 ALLOWED_DROPS 仅本次测试
    saved = ALLOWED_DROPS.copy()
    ALLOWED_DROPS.add(("a.py", 42))
    try:
        existing, new = _filter_allowed(holes)
    finally:
        ALLOWED_DROPS.clear()
        ALLOWED_DROPS.update(saved)

    assert ("a.py", 42) in existing, f"a.py:42 应为历史允许, got existing={existing}"
    assert ("b.py", 42) in [n[:2] for n in new], (
        f"b.py:42 必须被报为新增黑洞(不得被同 line 去重), got new={new}"
    )


if __name__ == "__main__":
    import sys
    rc = pytest.main([__file__, "-v"])
    sys.exit(rc)

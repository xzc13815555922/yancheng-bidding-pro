#!/usr/bin/env python3
"""
test_collect_metrics.py — CMMI Level 3 度量采集工具单测
2026-07-18 软件工程 P0-3 度量数据采集工具

测试覆盖：
  - metrics 表幂等创建
  - 8 项度量都能采集到
  - 报告生成成功
  - 重复调用不崩（多次写 metrics 表）
"""
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.utils.collect_metrics import (
    get_conn, insert_metric, collect_all, generate_report, METRICS_SCHEMA
)


def test_metrics_table_idempotent():
    """metrics 表能多次创建（幂等）"""
    conn = get_conn()
    # 检查表存在
    exists = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='metrics'"
    ).fetchone()[0]
    assert exists == 1, "metrics 表创建失败"
    # 再 get_conn() 一次，不应报错
    conn2 = get_conn()
    assert conn2 is not None
    conn.close()
    conn2.close()
    print("  ✅ metrics 表幂等")


def test_insert_metric():
    """单条插入能成功"""
    conn = get_conn()
    insert_metric(conn, "TEST", "测试度量", 99.9, "%", "test", {"foo": "bar"})
    conn.commit()
    row = conn.execute(
        "SELECT metric_code, metric_value, metric_unit, scope FROM metrics WHERE metric_code='TEST'"
    ).fetchone()
    assert row == ("TEST", 99.9, "%", "test"), f"插入失败: {row}"
    conn.close()
    print("  ✅ insert_metric OK")


def test_collect_all_metrics():
    """采集 8 项度量都能跑通"""
    results = collect_all(verbose=False)
    assert "M1" in results
    assert "M2" in results
    assert "M3" in results
    assert "M4" in results
    assert "M5" in results
    assert "M6" in results
    assert "M7" in results
    assert "M8" in results
    # M2 应有 4 张表的完整率
    assert len(results["M2"]) == 4, f"M2 应 4 表，实际 {len(results['M2'])}"
    # M8 应有 4 张表的行数
    assert len(results["M8"]) == 4, f"M8 应 4 表，实际 {len(results['M8'])}"
    # M3 应有匹配率（数字）
    assert isinstance(results["M3"]["rate"], float)
    print("  ✅ 8 项度量采集 OK")


def test_generate_report():
    """报告能生成"""
    results = collect_all(verbose=False)
    output = ROOT / "docs" / "metrics_report.md"
    result_path = generate_report(results, output)
    assert Path(result_path).exists()
    content = Path(result_path).read_text(encoding="utf-8")
    assert "CMMI Level 3" in content
    assert "M1" in content and "M8" in content
    print(f"  ✅ 报告生成: {result_path}")


def test_rerun_no_crash():
    """重复运行不崩（不抛异常）"""
    for _ in range(3):
        results = collect_all(verbose=False)
        assert results is not None
    print("  ✅ 3 次重复跑 OK")


if __name__ == "__main__":
    tests = [test_metrics_table_idempotent, test_insert_metric,
             test_collect_all_metrics, test_generate_report, test_rerun_no_crash]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'全部通过' if not failed else f'{failed} 项失败'} ({len(tests)} 个测试)")
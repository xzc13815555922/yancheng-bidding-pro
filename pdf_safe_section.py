#!/usr/bin/env python3
"""
pdf_safe_section.py — PDF 报告 per-section try/except 通用工具

P1-2026-07-07: 解决单站/单段异常让整份 PDF 崩溃或缺页
- safe_section(): 单点异常不中断整份 PDF，返回 fallback 段落
- SafeSectionTracker: 汇总 N 段中异常数量，报告末尾输出统计行

用法:
    from pdf_safe_section import safe_section, SafeSectionTracker

    tracker = SafeSectionTracker()

    elements = []
    for site in SITE_ORDER:
        block = safe_section(
            f"站点 {site}",
            lambda s=site: build_site_table(s),  # 注意闭包陷阱：用默认参数绑值
            tracker=tracker,
        )
        elements.extend(block)

    elements.extend(tracker.summary_paragraph())  # 末尾统计行
"""
from typing import Callable, List, Optional
import logging

logger = logging.getLogger(__name__)


def safe_section(
    name: str,
    fn: Callable,
    fallback_msg: str = "数据异常，已跳过",
    tracker: Optional["SafeSectionTracker"] = None,
) -> list:
    """
    执行 reportlab section，单点异常不中断整份 PDF。

    Args:
        name: 段落名（用于日志和 fallback 提示，如 "清单1-未来开标" 或 "站点 jszbcg"）
        fn: 构造段落的 callable，返回 list[Flowable]（或单个 Flowable，或 None）
        fallback_msg: 异常时显示给用户的提示
        tracker: 可选 SafeSectionTracker，自动记 1 次失败

    Returns:
        list[Flowable]: 成功时是 fn() 的返回；失败时是包含警告段落 + spacer 的 list
        ⚠️ 调用方区分"成功返回数据" vs "失败 fallback" 应检查列表里是否有 WARN_PARA 标记
           推荐用返回值首元素 isinstance(Paragraph) + 检查 style.name == 'WarnStyle'，
           或更简单：把 fallback 段落长度定为 2，且首元素是 Paragraph。
    """
    try:
        result = fn()
        if tracker is not None:
            tracker.add_ok(name)
        if result is None:
            return []
        if isinstance(result, list):
            return result
        # 单个 Flowable 也包成 list
        return [result]
    except Exception as e:
        logger.error(f"[PDF section] {name} 失败: {e}", exc_info=True)
        if tracker is not None:
            tracker.add_fail(name, e)
        # 失败时返回 1 个警告 Paragraph（不阻断后续 section）
        try:
            from reportlab.platypus import Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import cm

            styles = getSampleStyleSheet()
            warn_style = styles["Italic"].clone("WarnStyle")
            warn_style.fontSize = 9
            warn_style.textColor = "#B22222"  # 红色警示
            warn_style.leading = 12
            err_str = str(e)[:200].replace("\n", " ")
            return [
                Paragraph(f"⚠️ <b>{name}</b>：{fallback_msg}（{err_str}）", warn_style),
                Spacer(1, 0.3 * cm),
            ]
        except Exception as inner_e:
            # 极端情况：连 reportlab 都不可用（导入失败），返回空 list
            logger.error(f"[PDF section] {name} fallback 段落构造也失败: {inner_e}")
            return []


def is_fallback_block(block: list) -> bool:
    """判断 safe_section 返回的 list 是否是 fallback（异常 fallback）"""
    if not block or len(block) < 2:
        return False
    try:
        from reportlab.platypus import Paragraph
        if not isinstance(block[0], Paragraph):
            return False
        return getattr(block[0].style, "name", "") == "WarnStyle"
    except Exception:
        return False


class SafeSectionTracker:
    """记录 N 段成功/失败次数，报告末尾输出统计行"""

    def __init__(self):
        self.ok_count = 0
        self.fail_count = 0
        self.failed_sections: list = []  # [(name, error_str), ...]

    def add_ok(self, name: str):
        self.ok_count += 1

    def add_fail(self, name: str, error: Exception):
        self.fail_count += 1
        self.failed_sections.append((name, str(error)[:120]))

    @property
    def total(self):
        return self.ok_count + self.fail_count

    def summary_paragraph(self, prefix: str = "本次生成") -> list:
        """返回统计段落 list[Flowable]，可 append 到 story 末尾"""
        try:
            from reportlab.platypus import Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import cm

            styles = getSampleStyleSheet()
            s_note = styles["Italic"].clone("TrackerNote")
            s_note.fontSize = 8
            s_note.textColor = "#888888"

            if self.fail_count == 0:
                msg = f"{prefix} {self.total} 段，全部成功。"
            else:
                names = "、".join(n for n, _ in self.failed_sections[:5])
                if len(self.failed_sections) > 5:
                    names += f" 等 {len(self.failed_sections)} 个"
                msg = (
                    f"{prefix} {self.total} 段，成功 {self.ok_count} 段，"
                    f"异常 {self.fail_count} 段（{names}），详见 logs/xxx.log"
                )
            return [Spacer(1, 0.5 * cm), Paragraph(msg, s_note)]
        except Exception as e:
            logger.error(f"[tracker] summary_paragraph 失败: {e}")
            return []
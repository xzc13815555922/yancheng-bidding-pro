#!/usr/bin/env python3
"""
盐城市全域招标信息采集系统 Pro — 基础类
每个网站独立 DB，notices 主表包含：
  - 网站原生字段（全列，存入 raw_json 备份）
  - 标准化核心字段（跨站查询用）
  - 详情页补全字段（detail_fetched 状态追踪）
"""
import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


class SiteDB:
    """
    每网站独立 SQLite DB 管理器。
    notices 表：标准核心字段 + raw_json（原始 API 数据全列备份）。
    """

    # 标准核心 schema，所有网站共用；各站特有字段存 raw_json
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS notices (
        id              TEXT PRIMARY KEY,
        site            TEXT NOT NULL,
        notice_type     TEXT NOT NULL,   -- tender/intention/award/other
        source_url      TEXT,
        detail_url      TEXT,
        publish_date    DATE,
        crawl_time      DATETIME DEFAULT CURRENT_TIMESTAMP,
        project_name    TEXT NOT NULL,
        budget          REAL,
        budget_text     TEXT,
        budget_unit     TEXT,
        purchaser       TEXT,
        purchaser_raw   TEXT,
        open_date       DATETIME,        -- 开标时间（tender）
        deadline        DATETIME,        -- 报名截止（tender）
        expected_list   DATE,            -- 预计挂网（intention）
        winner          TEXT,            -- 中标单位（award）
        winning_amount  REAL,            -- 中标金额（award）
        region          TEXT,
        district_code   TEXT,
        raw_json        TEXT,            -- 完整原始 API 字段，JSON 序列化
        detail_fetched  INTEGER DEFAULT 0,  -- 0=待补全 1=已补全 2=补全失败
        is_duplicate    INTEGER DEFAULT 0,
        page_path       TEXT,            -- 本地缓存的详情页 MD 文件路径
        pdf_path        TEXT             -- 本地缓存的 PDF 文件路径（jszbcg）
    );
    CREATE INDEX IF NOT EXISTS idx_publish_date ON notices(publish_date);
    CREATE INDEX IF NOT EXISTS idx_notice_type  ON notices(notice_type);
    CREATE INDEX IF NOT EXISTS idx_region       ON notices(region);
    CREATE INDEX IF NOT EXISTS idx_detail       ON notices(detail_fetched);
    CREATE INDEX IF NOT EXISTS idx_site         ON notices(site);
    """

    def __init__(self, site_key: str):
        self.site_key = site_key
        self.db_path = DATA_DIR / f"{site_key}.db"
        self._conn: Optional[sqlite3.Connection] = None
        self._init()

    def _init(self):
        conn = self._get_conn()
        for stmt in self.SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        # 迁移：为已有 DB 补列（忽略已存在的错误）
        for col_def in [
            "page_path TEXT", "pdf_path TEXT",
            "std_district TEXT", "proj_minor_cat TEXT", "proj_major_cat TEXT",
        ]:
            try:
                conn.execute(f"ALTER TABLE notices ADD COLUMN {col_def}")
                conn.commit()
            except Exception:
                pass

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def insert(self, record: Dict) -> bool:
        """插入一条公告，id 冲突时 UPDATE（保留已有 detail_fetched 结果）。返回 True=新增，False=更新/跳过。"""
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT id, detail_fetched FROM notices WHERE id = ?", (record["id"],)
        ).fetchone()

        if existing:
            # 已存在：保留已完成的补全结果（detail_fetched=1）；若新记录含内联补全数据则更新
            new_dft = record.get("detail_fetched", 0)
            old_dft = existing["detail_fetched"]
            # 只有当旧记录尚未补全(0)且新记录已补全(1)时才覆盖补全字段
            if old_dft != 1 and new_dft == 1:
                # 更新全字段（含 purchaser/winner/winning_amount，从详情页补全的）
                # 用 helper 补齐 record 缺少的 key，避免 binding 错误
                update_cols = [
                    "notice_type", "publish_date", "project_name", "budget", "budget_text",
                    "budget_unit", "purchaser", "purchaser_raw", "open_date", "deadline",
                    "expected_list", "winner", "winning_amount", "region", "district_code",
                    "detail_url", "source_url", "raw_json", "detail_fetched", "page_path",
                ]
                params = self._build_params(record, update_cols)
                conn.execute("""
                    UPDATE notices SET
                        notice_type=:notice_type, publish_date=:publish_date,
                        project_name=:project_name, budget=:budget, budget_text=:budget_text,
                        budget_unit=:budget_unit, purchaser=:purchaser, purchaser_raw=:purchaser_raw,
                        open_date=:open_date, deadline=:deadline, expected_list=:expected_list,
                        winner=:winner, winning_amount=:winning_amount,
                        region=:region, district_code=:district_code,
                        detail_url=:detail_url, source_url=:source_url,
                        raw_json=:raw_json, detail_fetched=:detail_fetched,
                        page_path=COALESCE(:page_path, page_path)
                    WHERE id=:id
                """, {**params, "id": record["id"]})
            else:
                # 旧记录已补全 或 新记录未补全：保留旧补全结果，只更新基本信息
                # 不覆盖 purchaser/winner/winning_amount（这些是详情页补全的）
                update_cols = [
                    "notice_type", "publish_date", "project_name", "budget", "budget_text",
                    "budget_unit", "purchaser_raw", "open_date", "deadline",
                    "expected_list", "region", "district_code",
                    "detail_url", "source_url", "raw_json", "page_path",
                ]
                params = self._build_params(record, update_cols)
                conn.execute("""
                    UPDATE notices SET
                        notice_type=:notice_type, publish_date=:publish_date,
                        project_name=:project_name, budget=:budget, budget_text=:budget_text,
                        budget_unit=:budget_unit, purchaser_raw=:purchaser_raw,
                        open_date=:open_date, deadline=:deadline, expected_list=:expected_list,
                        region=:region, district_code=:district_code,
                        detail_url=:detail_url, source_url=:source_url,
                        raw_json=:raw_json,
                        page_path=COALESCE(:page_path, page_path)
                    WHERE id=:id
                """, {**params, "id": record["id"]})
            conn.commit()
            return False
        else:
            cols = [
                "id", "site", "notice_type", "source_url", "detail_url",
                "publish_date", "project_name", "budget", "budget_text", "budget_unit",
                "purchaser", "purchaser_raw", "open_date", "deadline", "expected_list",
                "winner", "winning_amount", "region", "district_code", "raw_json",
                "detail_fetched", "page_path", "pdf_path",
            ]
            placeholders = ", ".join(f":{c}" for c in cols)
            conn.execute(
                f"INSERT INTO notices ({', '.join(cols)}) VALUES ({placeholders})",
                self._build_params(record, cols),
            )
            conn.commit()
            return True

    @staticmethod
    def _build_params(record: Dict, cols: List[str]) -> Dict:
        """
        从 record 构建 INSERT/UPDATE 的参数字典。
        - 缺 key 补 None（避免 sqlite3 binding N 错误）
        - detail_fetched 缺省补 0
        """
        params = {}
        for c in cols:
            if c == "detail_fetched":
                params[c] = record.get(c, 0)
            else:
                params[c] = record.get(c)  # None when missing
        return params

    def count(self, notice_type: Optional[str] = None) -> int:
        conn = self._get_conn()
        if notice_type:
            return conn.execute(
                "SELECT COUNT(*) FROM notices WHERE notice_type=?", (notice_type,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]

    def count_by_type(self) -> Dict[str, int]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT notice_type, COUNT(*) FROM notices GROUP BY notice_type"
        ).fetchall()
        return dict(rows)

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


def make_id(project_name: str, publish_date: str, site: str) -> str:
    raw = f"{project_name}|{publish_date}|{site}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class BaseCrawler:
    """
    采集器基类。子类实现 crawl_type(notice_type, start_date, end_date) 方法。
    """
    SITE_KEY: str = ""   # DB 文件名，如 "jszbcg"
    SITE_NAME: str = ""  # 显示名称

    def __init__(self):
        assert self.SITE_KEY, "必须设置 SITE_KEY"
        self.db = SiteDB(self.SITE_KEY)
        self.logger = logging.getLogger(self.__class__.__name__)

    def crawl_all(self, start_date: str, end_date: str) -> Dict:
        """采集所有公告类型，汇总结果。"""
        totals = {"total": 0, "new": 0, "by_type": {}}
        for ntype in ["tender", "intention", "award", "other"]:
            try:
                result = self.crawl_type(ntype, start_date, end_date)
                totals["total"] += result.get("total", 0)
                totals["new"] += result.get("new", 0)
                totals["by_type"][ntype] = result
            except NotImplementedError:
                pass
            except Exception as e:
                self.logger.error(f"{self.SITE_NAME} crawl_type={ntype} 失败: {e}")
        return totals

    def crawl_type(self, notice_type: str, start_date: str, end_date: str) -> Dict:
        raise NotImplementedError

    def save(self, record: Dict) -> bool:
        return self.db.insert(record)

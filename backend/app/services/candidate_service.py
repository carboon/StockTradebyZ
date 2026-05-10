"""
Candidate Persistence Service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
阶段7：候选数据持久化服务

将明日之星候选结果从文件系统迁移到数据库。
核心功能：
1. 保存候选数据到数据库
2. 从数据库读取候选数据
3. 获取最新候选日期
4. 候选历史数据管理
"""
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
from sqlalchemy import select, func, and_, case, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Candidate, DailyB1Check, Stock, StockDaily
from app.services.tushare_service import TushareService

ROOT = Path(__file__).parent.parent.parent.parent
logger = logging.getLogger(__name__)


class CandidateService:
    """候选数据持久化服务

    负责将候选结果从文件系统迁移到数据库，并提供统一的读写接口。
    """

    def __init__(self, db: Optional[Session] = None):
        self.db = db or SessionLocal()
        self._owns_session = db is None
        self.tushare_service = TushareService()
        self._raw_daily_cache: dict[str, dict[date, dict[str, Optional[float]]]] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._owns_session:
            self.db.close()

    def save_candidates(
        self,
        pick_date: str,
        candidates: List[Dict[str, Any]],
        strategy: str = "b1",
        clean_existing: bool = True,
    ) -> int:
        """保存候选数据到数据库

        Args:
            pick_date: 选拔日期 (YYYY-MM-DD)
            candidates: 候选股票列表
            strategy: 策略类型
            clean_existing: 是否清理已有数据

        Returns:
            保存的记录数
        """
        try:
            pick_dt = date.fromisoformat(pick_date)
        except ValueError:
            logger.error(f"无效的日期格式: {pick_date}")
            return 0

        # 清理已有数据
        if clean_existing:
            self.db.query(Candidate).filter(
                Candidate.pick_date == pick_dt
            ).delete(synchronize_session=False)
            self.db.commit()

        # 收集股票代码用于同步名称
        codes = [str(c.get("code", "")).zfill(6) for c in candidates if c.get("code")]
        if codes:
            try:
                self.tushare_service.sync_stock_names_to_db(self.db, codes)
            except Exception as e:
                logger.warning(f"同步股票名称失败: {e}")

        # 构建记录
        rows = []
        for item in candidates:
            code = str(item.get("code", "")).zfill(6)
            if not code or code == "000000":
                continue

            # 从 extra 中提取详细信息
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}

            rows.append(
                Candidate(
                    pick_date=pick_dt,
                    code=code,
                    strategy=item.get("strategy", strategy),
                    close_price=float(item.get("close", 0)) if item.get("close") is not None else None,
                    turnover=float(item.get("turnover_n", 0)) if item.get("turnover_n") is not None else None,
                    b1_passed=item.get("strategy") == "b1" or item.get("b1_passed", False),
                    kdj_j=float(extra.get("kdj_j", 0)) if extra.get("kdj_j") is not None else None,
                )
            )

        if rows:
            self.db.add_all(rows)
            self.db.commit()
            logger.info(f"保存候选数据: pick_date={pick_date}, count={len(rows)}")

        if clean_existing or rows:
            self.recalculate_consecutive_metrics(self.db)

        return len(rows)

    @staticmethod
    def recalculate_consecutive_metrics(db: Session, *, commit: bool = True) -> Dict[str, int]:
        """重算所有候选的连续候选次数及每日连续候选数。"""
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(
                text(
                    """
                    WITH ordered_days AS (
                        SELECT trade_date,
                               LAG(trade_date) OVER (ORDER BY trade_date) AS prev_trade_date
                        FROM (
                            SELECT DISTINCT trade_date
                            FROM stock_daily
                        ) AS distinct_days
                    ),
                    candidate_prev AS (
                        SELECT
                            c.id,
                            c.code,
                            c.pick_date,
                            od.prev_trade_date,
                            LAG(c.pick_date) OVER (PARTITION BY c.code ORDER BY c.pick_date, c.id) AS prev_candidate_date
                        FROM candidates c
                        LEFT JOIN ordered_days od
                          ON od.trade_date = c.pick_date
                    ),
                    candidate_groups AS (
                        SELECT
                            id,
                            code,
                            pick_date,
                            SUM(
                                CASE
                                    WHEN prev_trade_date IS NOT NULL AND prev_candidate_date = prev_trade_date THEN 0
                                    ELSE 1
                                END
                            ) OVER (PARTITION BY code ORDER BY pick_date, id ROWS UNBOUNDED PRECEDING) AS grp
                        FROM candidate_prev
                    ),
                    candidate_streaks AS (
                        SELECT
                            id,
                            ROW_NUMBER() OVER (PARTITION BY code, grp ORDER BY pick_date, id) AS consecutive_days
                        FROM candidate_groups
                    )
                    UPDATE candidates AS c
                    SET consecutive_days = s.consecutive_days
                    FROM candidate_streaks AS s
                    WHERE c.id = s.id
                    """
                )
            )
            db.execute(
                text(
                    """
                    UPDATE tomorrow_star_runs AS r
                    SET consecutive_candidate_count = COALESCE(stats.consecutive_candidate_count, 0)
                    FROM (
                        SELECT pick_date, COUNT(*) AS consecutive_candidate_count
                        FROM candidates
                        WHERE consecutive_days >= 2
                        GROUP BY pick_date
                    ) AS stats
                    WHERE r.pick_date = stats.pick_date
                    """
                )
            )
            db.execute(
                text(
                    """
                    UPDATE tomorrow_star_runs
                    SET consecutive_candidate_count = 0
                    WHERE pick_date NOT IN (
                        SELECT DISTINCT pick_date
                        FROM candidates
                        WHERE consecutive_days >= 2
                    )
                    """
                )
            )

            if commit:
                db.commit()
            else:
                db.flush()

            from app.models import TomorrowStarRun

            candidate_rows = int(db.query(func.count(Candidate.id)).scalar() or 0)
            run_rows = int(db.query(func.count(TomorrowStarRun.id)).scalar() or 0)
            days_with_consecutive_candidates = int(
                db.query(func.count(func.distinct(Candidate.pick_date)))
                .filter(Candidate.consecutive_days >= 2)
                .scalar()
                or 0
            )
            return {
                "candidate_rows": candidate_rows,
                "run_rows": run_rows,
                "days_with_consecutive_candidates": days_with_consecutive_candidates,
            }

        trade_dates = (
            db.execute(
                select(StockDaily.trade_date)
                .distinct()
                .order_by(StockDaily.trade_date.asc())
            )
            .scalars()
            .all()
        )
        prev_trade_date_map = {
            trade_dates[index]: trade_dates[index - 1]
            for index in range(1, len(trade_dates))
        }

        rows = (
            db.query(Candidate)
            .order_by(Candidate.code.asc(), Candidate.pick_date.asc(), Candidate.id.asc())
            .all()
        )

        last_seen_date_by_code: Dict[str, date] = {}
        last_streak_by_code: Dict[str, int] = {}
        consecutive_candidate_count_by_date: Dict[date, int] = {}

        for row in rows:
            expected_previous_trade_date = prev_trade_date_map.get(row.pick_date)
            previous_candidate_date = last_seen_date_by_code.get(row.code)
            previous_streak = last_streak_by_code.get(row.code, 0)

            if expected_previous_trade_date and previous_candidate_date == expected_previous_trade_date:
                streak = previous_streak + 1
            else:
                streak = 1

            row.consecutive_days = streak
            last_seen_date_by_code[row.code] = row.pick_date
            last_streak_by_code[row.code] = streak

            if streak >= 2:
                consecutive_candidate_count_by_date[row.pick_date] = (
                    consecutive_candidate_count_by_date.get(row.pick_date, 0) + 1
                )

        from app.models import TomorrowStarRun
        run_rows = db.query(TomorrowStarRun).all()
        for run in run_rows:
            run.consecutive_candidate_count = int(consecutive_candidate_count_by_date.get(run.pick_date, 0) or 0)

        if commit:
            db.commit()
        else:
            db.flush()
        return {
            "candidate_rows": len(rows),
            "run_rows": len(run_rows),
            "days_with_consecutive_candidates": len(consecutive_candidate_count_by_date),
        }

    def load_candidates(
        self,
        pick_date: Optional[str] = None,
        limit: int = 100,
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """从数据库读取候选数据

        Args:
            pick_date: 选拔日期，None 表示读取最新日期
            limit: 返回数量限制

        Returns:
            (pick_date, candidates) 元组
        """
        if pick_date:
            try:
                target_date = date.fromisoformat(pick_date)
            except ValueError:
                target_date = None
        else:
            # 获取最新日期
            target_date = self.get_latest_candidate_date()

        if not target_date:
            return None, []

        # 查询候选数据
        query = (
            self.db.query(
                Candidate.code,
                Candidate.strategy,
                Candidate.close_price,
                Candidate.turnover,
                Candidate.b1_passed,
                Candidate.kdj_j,
                Candidate.consecutive_days,
                Stock.name,
                StockDaily.open.label("open_price"),
                StockDaily.close.label("daily_close_price"),
                StockDaily.turnover_rate,
                StockDaily.volume_ratio,
                DailyB1Check.active_pool_rank,
            )
            .join(Stock, Candidate.code == Stock.code, isouter=True)
            .join(
                StockDaily,
                and_(
                    Candidate.code == StockDaily.code,
                    Candidate.pick_date == StockDaily.trade_date,
                ),
                isouter=True,
            )
            .join(
                DailyB1Check,
                and_(
                    Candidate.code == DailyB1Check.code,
                    Candidate.pick_date == DailyB1Check.check_date,
                ),
                isouter=True,
            )
            .filter(Candidate.pick_date == target_date)
            .order_by(Candidate.id)
            .limit(limit)
        )

        candidates = []
        for row in query.all():
            raw_snapshot = None
            if (
                row.open_price is None
                or row.daily_close_price is None
                or row.turnover_rate is None
                or row.volume_ratio is None
            ):
                raw_snapshot = self._load_raw_daily_snapshot(str(row.code).zfill(6), target_date)
            close_price = float(row.close_price) if row.close_price is not None else (
                float(row.daily_close_price) if row.daily_close_price is not None else (
                    raw_snapshot.get("close") if raw_snapshot else None
                )
            )
            open_price = float(row.open_price) if row.open_price is not None else (
                raw_snapshot.get("open") if raw_snapshot else None
            )
            change_pct = None
            if open_price is not None and close_price is not None and open_price > 0:
                change_pct = (close_price - open_price) / open_price * 100

            candidates.append({
                "code": row.code,
                "name": row.name,
                "strategy": row.strategy,
                "open": open_price,
                "close": close_price,
                "change_pct": change_pct,
                "turnover_n": float(row.turnover) if row.turnover is not None else None,
                "turnover_rate": float(row.turnover_rate) if row.turnover_rate is not None else (
                    raw_snapshot.get("turnover_rate") if raw_snapshot else None
                ),
                "volume_ratio": float(row.volume_ratio) if row.volume_ratio is not None else (
                    raw_snapshot.get("volume_ratio") if raw_snapshot else None
                ),
                "active_pool_rank": int(row.active_pool_rank) if row.active_pool_rank is not None else None,
                "b1_passed": row.b1_passed,
                "kdj_j": float(row.kdj_j) if row.kdj_j is not None else None,
                "consecutive_days": int(row.consecutive_days or 1),
            })

        self._fill_missing_active_pool_ranks(target_date, candidates)
        return target_date.isoformat(), candidates

    @staticmethod
    def _fill_missing_active_pool_ranks(pick_date: date, candidates: List[Dict[str, Any]]) -> None:
        missing_codes = {
            str(item.get("code", "")).zfill(6)
            for item in candidates
            if item.get("active_pool_rank") is None and item.get("code")
        }
        if not missing_codes:
            return

        try:
            from app.services.analysis_service import analysis_service

            target_ts = pd.Timestamp(pick_date).normalize()
            preselect_cfg = analysis_service._load_preselect_config()
            rankings = analysis_service._safe_build_active_pool_rankings(
                start_ts=target_ts,
                end_ts=target_ts,
                preselect_cfg=preselect_cfg,
                target_codes=missing_codes,
            )
            if not rankings:
                return
            for item in candidates:
                code = str(item.get("code", "")).zfill(6)
                if item.get("active_pool_rank") is None:
                    rank = rankings.get(code, {}).get(target_ts)
                    item["active_pool_rank"] = int(rank) if rank is not None else None
        except Exception as exc:
            logger.warning("补齐候选活跃排名失败: pick_date=%s error=%s", pick_date, exc)

    def _load_raw_daily_snapshot(self, code: str, pick_date: date) -> Optional[dict[str, Optional[float]]]:
        normalized_code = str(code or "").zfill(6)
        cached = self._raw_daily_cache.get(normalized_code)
        if cached is None:
            csv_path = Path(settings.raw_data_dir) / f"{normalized_code}.csv"
            if not csv_path.exists():
                self._raw_daily_cache[normalized_code] = {}
                return None
            try:
                df = pd.read_csv(csv_path)
                df["date"] = pd.to_datetime(df["date"]).dt.date
                cached = {
                    trade_date: {
                        "open": self._to_optional_float(row.get("open")),
                        "close": self._to_optional_float(row.get("close")),
                        "turnover_rate": self._to_optional_float(row.get("turnover_rate")),
                        "volume_ratio": self._to_optional_float(row.get("volume_ratio")),
                    }
                    for trade_date, row in df.set_index("date").iterrows()
                }
            except Exception as exc:
                logger.warning("读取原始行情失败: code=%s error=%s", normalized_code, exc)
                cached = {}
            self._raw_daily_cache[normalized_code] = cached
        return cached.get(pick_date)

    @staticmethod
    def _to_optional_float(value: Any) -> Optional[float]:
        if value is None or pd.isna(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def get_latest_candidate_date(self) -> Optional[date]:
        """获取最新候选日期

        Returns:
            最新候选日期
        """
        result = self.db.execute(
            select(Candidate.pick_date)
            .order_by(Candidate.pick_date.desc())
            .limit(1)
        ).first()

        return result[0] if result else None

    def get_candidate_dates(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取候选历史日期列表

        Args:
            limit: 返回数量限制

        Returns:
            日期历史列表
        """
        # 统计每天候选数量
        subquery = (
            self.db.query(
                Candidate.pick_date,
                func.count(Candidate.id).label("count"),
            )
            .group_by(Candidate.pick_date)
            .order_by(Candidate.pick_date.desc())
            .limit(limit)
            .subquery()
        )

        # 查询每天“趋势启动”数量。
        # 这里的 pass 字段用于 TomorrowStar 左侧“趋势启动数”，
        # 不能再复用 Candidate.b1_passed，否则会退化成“候选数”。
        from app.models import AnalysisResult
        pass_query = (
            self.db.query(
                AnalysisResult.pick_date.label("pick_date"),
                func.count(AnalysisResult.id).label("pass_count"),
            )
            .filter(AnalysisResult.signal_type == "trend_start")
            .group_by(AnalysisResult.pick_date)
            .subquery()
        )

        query = (
            self.db.query(
                subquery.c.pick_date,
                subquery.c.count,
                pass_query.c.pass_count,
                func.sum(
                    case((Candidate.consecutive_days >= 2, 1), else_=0)
                ).label("consecutive_candidate_count"),
            )
            .outerjoin(pass_query, subquery.c.pick_date == pass_query.c.pick_date)
            .outerjoin(Candidate, Candidate.pick_date == subquery.c.pick_date)
            .group_by(subquery.c.pick_date, subquery.c.count, pass_query.c.pass_count)
            .order_by(subquery.c.pick_date.desc())
        )

        history = []
        for row in query.all():
            history.append({
                "date": row.pick_date.isoformat(),
                "count": row.count or 0,
                "pass": row.pass_count or 0,
                "consecutive_candidate_count": int(row.consecutive_candidate_count or 0),
            })

        return history

    def get_candidate_count(self, pick_date: Optional[str] = None) -> int:
        """获取候选数量

        Args:
            pick_date: 选拔日期，None 表示查询所有

        Returns:
            候选数量
        """
        query = self.db.query(func.count(Candidate.id))

        if pick_date:
            try:
                target_date = date.fromisoformat(pick_date)
                query = query.filter(Candidate.pick_date == target_date)
            except ValueError:
                pass

        return query.scalar() or 0

    def migrate_from_file(self, file_path: Optional[Path] = None) -> int:
        """从文件迁移候选数据到数据库

        Args:
            file_path: 文件路径，默认使用 candidates_latest.json

        Returns:
            迁移的记录数
        """
        if file_path is None:
            file_path = ROOT / settings.candidates_dir / "candidates_latest.json"

        if not file_path.exists():
            logger.warning(f"候选文件不存在: {file_path}")
            return 0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            pick_date_text = data.get("pick_date")
            if not pick_date_text:
                logger.error(f"文件中缺少 pick_date: {file_path}")
                return 0

            candidates = data.get("candidates", [])
            if not isinstance(candidates, list):
                logger.error(f"无效的 candidates 格式: {file_path}")
                return 0

            return self.save_candidates(pick_date_text, candidates)

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"读取候选文件失败: {e}")
            return 0

    def migrate_all_history_files(self, limit: int = 100) -> Dict[str, Any]:
        """迁移所有历史候选文件到数据库

        Args:
            limit: 处理文件数量限制

        Returns:
            迁移统计信息
        """
        candidates_dir = ROOT / settings.candidates_dir
        history_files = sorted(
            candidates_dir.glob("candidates_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        # 排除 latest 文件
        history_files = [f for f in history_files if f.name != "candidates_latest.json"]

        success_count = 0
        failed_count = 0
        total_count = 0
        processed_dates = []

        for file_path in history_files[:limit]:
            try:
                count = self.migrate_from_file(file_path)
                if count > 0:
                    success_count += 1
                    total_count += count
                    processed_dates.append(file_path.stem)
                else:
                    failed_count += 1
            except Exception as e:
                logger.error(f"迁移文件失败 {file_path}: {e}")
                failed_count += 1

        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "total_candidates": total_count,
            "processed_dates": processed_dates,
        }

    def delete_candidates(self, pick_date: str) -> int:
        """删除指定日期的候选数据

        Args:
            pick_date: 选拔日期

        Returns:
            删除的记录数
        """
        try:
            pick_dt = date.fromisoformat(pick_date)
        except ValueError:
            logger.error(f"无效的日期格式: {pick_date}")
            return 0

        count = self.db.query(Candidate).filter(
            Candidate.pick_date == pick_dt
        ).delete(synchronize_session=False)

        self.db.commit()
        logger.info(f"删除候选数据: pick_date={pick_date}, count={count}")

        return count

    def get_db_status(self) -> Dict[str, Any]:
        """获取数据库中候选数据的状态

        Returns:
            状态信息字典
        """
        # 最新日期
        latest_date = self.get_latest_candidate_date()

        # 总记录数
        total_count = self.db.query(func.count(Candidate.id)).scalar() or 0

        # 日期数量
        date_count = self.db.query(
            func.count(func.distinct(Candidate.pick_date))
        ).scalar() or 0

        # 各日期统计
        date_stats = self.get_candidate_dates(limit=30)

        return {
            "latest_date": latest_date.isoformat() if latest_date else None,
            "total_count": total_count,
            "date_count": date_count,
            "recent_dates": date_stats[:10],
        }


# 全局实例
_candidate_service: Optional[CandidateService] = None


def get_candidate_service() -> CandidateService:
    """获取候选服务单例"""
    global _candidate_service
    if _candidate_service is None:
        _candidate_service = CandidateService()
    return _candidate_service

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

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Candidate, Stock
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

        return len(rows)

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
                Stock.name,
            )
            .join(Stock, Candidate.code == Stock.code, isouter=True)
            .filter(Candidate.pick_date == target_date)
            .order_by(Candidate.id)
            .limit(limit)
        )

        candidates = []
        for row in query.all():
            candidates.append({
                "code": row.code,
                "name": row.name,
                "strategy": row.strategy,
                "close": float(row.close_price) if row.close_price is not None else None,
                "turnover_n": float(row.turnover) if row.turnover is not None else None,
                "b1_passed": row.b1_passed,
                "kdj_j": float(row.kdj_j) if row.kdj_j is not None else None,
            })

        return target_date.isoformat(), candidates

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

        # 查询每天通过的数量
        pass_query = (
            self.db.query(
                Candidate.pick_date,
                func.count(Candidate.id).label("pass_count"),
            )
            .filter(Candidate.b1_passed == True)
            .group_by(Candidate.pick_date)
            .subquery()
        )

        query = (
            self.db.query(
                subquery.c.pick_date,
                subquery.c.count,
                pass_query.c.pass_count,
            )
            .outerjoin(pass_query, subquery.c.pick_date == pass_query.c.pick_date)
            .order_by(subquery.c.pick_date.desc())
        )

        history = []
        for row in query.all():
            history.append({
                "date": row.pick_date.isoformat(),
                "count": row.count or 0,
                "pass": row.pass_count or 0,
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

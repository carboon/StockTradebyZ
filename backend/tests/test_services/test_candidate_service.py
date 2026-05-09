"""
测试候选数据持久化服务

验证候选数据可以正确地从文件迁移到数据库，并支持数据库优先的读取模式。
"""
import json
import pytest
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.services.candidate_service import CandidateService
from app.models import Candidate, Stock
from app.services.tushare_service import TushareService


@pytest.fixture
def db():
    """隔离的数据库会话。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def sample_candidates():
    """样例候选数据"""
    return [
        {
            "code": "600519",
            "strategy": "b1",
            "close": 1680.50,
            "turnover_n": 1500000000,
            "b1_passed": True,
            "extra": {"kdj_j": 25.5},
        },
        {
            "code": "000858",
            "strategy": "b1",
            "close": 125.30,
            "turnover_n": 800000000,
            "b1_passed": True,
            "extra": {"kdj_j": 18.2},
        },
        {
            "code": "300750",
            "strategy": "b1",
            "close": 280.90,
            "turnover_n": 500000000,
            "b1_passed": True,
            "extra": {"kdj_j": 32.1},
        },
    ]


class TestCandidateService:
    """测试候选数据服务"""

    @pytest.fixture(autouse=True)
    def _stub_tushare_sync(self, monkeypatch):
        monkeypatch.setattr(
            TushareService,
            "sync_stock_names_to_db",
            lambda self, db, codes: None,
        )

    def test_save_candidates(self, db, sample_candidates):
        """测试保存候选数据到数据库"""
        service = CandidateService(db)

        # 清理测试数据
        db.query(Candidate).filter(
            Candidate.pick_date == date(2024, 5, 1)
        ).delete(synchronize_session=False)
        db.commit()

        # 保存候选数据
        count = service.save_candidates(
            pick_date="2024-05-01",
            candidates=sample_candidates,
            strategy="b1",
            clean_existing=False,
        )

        assert count == 3

        # 验证数据库中的记录
        records = db.query(Candidate).filter(
            Candidate.pick_date == date(2024, 5, 1)
        ).all()

        assert len(records) == 3
        assert records[0].code == "600519"
        assert records[0].strategy == "b1"
        assert records[0].b1_passed is True

    def test_load_candidates(self, db, sample_candidates):
        """测试从数据库加载候选数据"""
        service = CandidateService(db)

        # 清理并插入测试数据
        db.query(Candidate).filter(
            Candidate.pick_date == date(2024, 5, 2)
        ).delete(synchronize_session=False)
        db.commit()

        service.save_candidates(
            pick_date="2024-05-02",
            candidates=sample_candidates,
            strategy="b1",
        )

        # 加载候选数据
        pick_date, candidates = service.load_candidates("2024-05-02")

        assert pick_date == "2024-05-02"
        assert len(candidates) == 3
        assert candidates[0]["code"] == "600519"

    def test_load_candidates_falls_back_to_raw_csv_open_price(self, db, tmp_path, monkeypatch):
        """当 stock_daily 缺失时，候选列表应回退到原始 CSV 补开盘价。"""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "688779.csv").write_text(
            "date,open,close,high,low,volume\n"
            "2026-02-04,10.48,9.91,10.60,9.80,123456.0\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(settings, "raw_data_dir", raw_dir)

        db.add(Stock(code="688779", name="五矿新能", market="SH"))
        db.add(
            Candidate(
                pick_date=date(2026, 2, 4),
                code="688779",
                strategy="b1",
                close_price=9.91,
                turnover=199154913.3123,
                b1_passed=True,
                kdj_j=-3.215705,
                consecutive_days=3,
            )
        )
        db.commit()

        pick_date, candidates = CandidateService(db).load_candidates("2026-02-04")

        assert pick_date == "2026-02-04"
        assert len(candidates) == 1
        assert candidates[0]["code"] == "688779"
        assert candidates[0]["name"] == "五矿新能"
        assert candidates[0]["open"] == 10.48
        assert candidates[0]["close"] == 9.91

    def test_get_latest_candidate_date(self, db, sample_candidates):
        """测试获取最新候选日期"""
        service = CandidateService(db)

        # 插入不同日期的数据
        service.save_candidates(
            pick_date="2024-05-01",
            candidates=sample_candidates[:1],
            strategy="b1",
        )
        service.save_candidates(
            pick_date="2024-05-02",
            candidates=sample_candidates[:1],
            strategy="b1",
        )

        latest = service.get_latest_candidate_date()
        assert latest == date(2024, 5, 2)

    def test_get_candidate_dates(self, db, sample_candidates):
        """测试获取候选日期历史"""
        service = CandidateService(db)

        # 插入测试数据
        service.save_candidates(
            pick_date="2024-05-01",
            candidates=sample_candidates[:1],
            strategy="b1",
        )
        service.save_candidates(
            pick_date="2024-05-02",
            candidates=sample_candidates[:2],
            strategy="b1",
        )

        history = service.get_candidate_dates(limit=10)

        assert len(history) >= 2
        # 最新的应该在前面
        dates = [h["date"] for h in history]
        assert "2024-05-02" in dates
        assert "2024-05-01" in dates

    def test_migrate_from_file(self, db, sample_candidates, tmp_path):
        """测试从文件迁移候选数据"""
        # 创建临时文件
        temp_file = tmp_path / "candidates_temp.json"
        data = {
            "pick_date": "2024-05-03",
            "candidates": sample_candidates,
        }
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        service = CandidateService(db)

        # 迁移文件
        count = service.migrate_from_file(temp_file)

        assert count == 3

        # 验证数据库记录
        records = db.query(Candidate).filter(
            Candidate.pick_date == date(2024, 5, 3)
        ).all()

        assert len(records) == 3

    def test_delete_candidates(self, db, sample_candidates):
        """测试删除候选数据"""
        service = CandidateService(db)

        # 插入测试数据
        service.save_candidates(
            pick_date="2024-05-01",
            candidates=sample_candidates,
            strategy="b1",
        )

        # 删除数据
        count = service.delete_candidates("2024-05-01")

        assert count == 3

        # 验证删除
        records = db.query(Candidate).filter(
            Candidate.pick_date == date(2024, 5, 1)
        ).all()

        assert len(records) == 0

    def test_get_db_status(self, db, sample_candidates):
        """测试获取数据库状态"""
        service = CandidateService(db)

        # 插入测试数据
        service.save_candidates(
            pick_date="2024-05-01",
            candidates=sample_candidates,
            strategy="b1",
        )

        status = service.get_db_status()

        assert status["latest_date"] == "2024-05-01"
        assert status["total_count"] == 3
        assert status["date_count"] == 1

    def test_load_candidates_latest(self, db, sample_candidates):
        """测试加载最新候选数据（不指定日期）"""
        service = CandidateService(db)

        # 插入多天数据
        service.save_candidates(
            pick_date="2024-05-01",
            candidates=sample_candidates[:1],
            strategy="b1",
        )
        service.save_candidates(
            pick_date="2024-05-02",
            candidates=sample_candidates[:2],
            strategy="b1",
        )

        # 不指定日期，应返回最新日期的数据
        pick_date, candidates = service.load_candidates()

        assert pick_date == "2024-05-02"
        assert len(candidates) == 2

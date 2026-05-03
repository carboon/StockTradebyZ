#!/usr/bin/env python
"""
测试 analysis_service 的数据库优先读取功能

验证候选数据可以优先从数据库读取。
"""
import sys
from pathlib import Path

# 添加 backend 目录到 Python 路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.services.candidate_service import CandidateService
from app.services.analysis_service import analysis_service
from app.models import Candidate


def test_db_priority_read():
    """测试数据库优先读取"""
    db = SessionLocal()

    try:
        service = CandidateService(db)

        # 清理并插入测试数据
        db.query(Candidate).filter(
            Candidate.pick_date == "2024-06-01"
        ).delete(synchronize_session=False)
        db.commit()

        test_candidates = [
            {
                "code": "600519",
                "strategy": "b1",
                "close": 1700.0,
                "turnover_n": 1000000000,
                "b1_passed": True,
                "extra": {"kdj_j": 20.5},
            },
            {
                "code": "000858",
                "strategy": "b1",
                "close": 130.0,
                "turnover_n": 500000000,
                "b1_passed": True,
                "extra": {"kdj_j": 15.0},
            },
        ]

        count = service.save_candidates(
            pick_date="2024-06-01",
            candidates=test_candidates,
            strategy="b1",
        )
        print(f"插入测试数据: {count} 条")

        # 测试 get_latest_candidate_date
        print("\n测试 get_latest_candidate_date...")
        latest = analysis_service.get_latest_candidate_date()
        print(f"  最新日期: {latest}")

        # 测试 load_candidate_codes
        print("\n测试 load_candidate_codes...")
        pick_date, codes = analysis_service.load_candidate_codes("2024-06-01")
        print(f"  日期: {pick_date}")
        print(f"  代码: {codes}")

        # 测试 get_candidates_history
        print("\n测试 get_candidates_history...")
        history = analysis_service.get_candidates_history(limit=10)
        print(f"  历史数量: {len(history)}")
        for h in history[:3]:
            print(f"    - {h['date']}: {h['count']} 只候选, {h['pass']} 通过")

        # 验证数据确实来自数据库
        assert pick_date == "2024-06-01", f"期望日期 2024-06-01, 实际 {pick_date}"
        assert "600519" in codes, f"期望包含 600519, 实际 {codes}"
        assert "000858" in codes, f"期望包含 000858, 实际 {codes}"

        print("\n所有测试通过! 数据库优先读取功能正常")

        # 清理测试数据
        service.delete_candidates("2024-06-01")
        print("测试数据已清理")

        return True

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        db.close()


if __name__ == "__main__":
    success = test_db_priority_read()
    sys.exit(0 if success else 1)

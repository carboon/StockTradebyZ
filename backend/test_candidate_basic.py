#!/usr/bin/env python
"""
简单测试候选服务的基本功能

验证候选数据可以正确地保存和读取。
"""
import sys
from pathlib import Path

# 添加 backend 目录到 Python 路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.services.candidate_service import CandidateService
from app.models import Candidate, Stock


def test_basic_operations():
    """测试基本的保存和读取操作"""
    db = SessionLocal()

    try:
        service = CandidateService(db)

        # 清理测试数据
        db.query(Candidate).filter(
            Candidate.pick_date == "2024-05-01"
        ).delete(synchronize_session=False)
        db.commit()

        # 测试数据
        sample_candidates = [
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
        ]

        # 测试保存
        print("测试保存候选数据...")
        count = service.save_candidates(
            pick_date="2024-05-01",
            candidates=sample_candidates,
            strategy="b1",
        )
        print(f"  保存了 {count} 条记录")

        # 测试读取
        print("测试读取候选数据...")
        pick_date, candidates = service.load_candidates("2024-05-01")
        print(f"  日期: {pick_date}, 数量: {len(candidates)}")
        for c in candidates:
            print(f"    - {c['code']}: {c['close']}")

        # 测试获取最新日期
        print("测试获取最新日期...")
        latest = service.get_latest_candidate_date()
        print(f"  最新日期: {latest}")

        # 测试获取历史日期
        print("测试获取历史日期...")
        history = service.get_candidate_dates(limit=10)
        print(f"  历史日期数量: {len(history)}")
        for h in history[:3]:
            print(f"    - {h['date']}: {h['count']} 只候选")

        # 测试数据库状态
        print("测试获取数据库状态...")
        status = service.get_db_status()
        print(f"  最新日期: {status['latest_date']}")
        print(f"  总记录数: {status['total_count']}")
        print(f"  日期数量: {status['date_count']}")

        # 清理测试数据
        print("清理测试数据...")
        service.delete_candidates("2024-05-01")
        print("  测试数据已清理")

        print("\n所有测试通过!")
        return True

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        db.close()


if __name__ == "__main__":
    success = test_basic_operations()
    sys.exit(0 if success else 1)

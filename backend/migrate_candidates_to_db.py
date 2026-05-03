#!/usr/bin/env python
"""
迁移候选数据到数据库

将 data/candidates/ 目录下的所有候选文件数据迁移到数据库。
用法：
    python backend/migrate_candidates_to_db.py [--latest-only]
"""
import argparse
import sys
from pathlib import Path

# 添加 backend 目录到 Python 路径
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.services.candidate_service import CandidateService


def main():
    parser = argparse.ArgumentParser(description="迁移候选数据到数据库")
    parser.add_argument("--latest-only", action="store_true", help="只迁移最新文件")
    parser.add_argument("--limit", type=int, default=100, help="迁移文件数量限制")
    args = parser.parse_args()

    service = CandidateService()

    if args.latest_only:
        print("迁移最新候选文件...")
        count = service.migrate_from_file()
        print(f"迁移完成: {count} 条记录")
    else:
        print("迁移所有历史候选文件...")
        result = service.migrate_all_history_files(limit=args.limit)
        print(f"迁移完成:")
        print(f"  成功文件: {result['success_count']}")
        print(f"  失败文件: {result['failed_count']}")
        print(f"  总记录数: {result['total_candidates']}")

    # 显示数据库状态
    print("\n数据库状态:")
    status = service.get_db_status()
    print(f"  最新日期: {status['latest_date']}")
    print(f"  总记录数: {status['total_count']}")
    print(f"  日期数量: {status['date_count']}")


if __name__ == "__main__":
    main()

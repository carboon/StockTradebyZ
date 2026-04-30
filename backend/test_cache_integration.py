#!/usr/bin/env python3
"""
缓存集成验证脚本

验证分析缓存服务的基本功能。
"""
import sys
import json
from pathlib import Path

# 添加 backend 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.services.analysis_cache import analysis_cache, AnalysisCacheService


def test_cache_key_generation():
    """测试缓存键生成"""
    print("测试缓存键生成...")

    key1 = analysis_cache.make_cache_key("600000", "2024-01-15")
    assert key1 == "600000_2024-01-15_v1", f"Expected '600000_2024-01-15_v1', got '{key1}'"

    key2 = analysis_cache.make_watchlist_cache_key(123, "2024-01-15")
    assert key2 == "watchlist_123_2024-01-15", f"Expected 'watchlist_123_2024-01-15', got '{key2}'"

    print("  ✓ 缓存键生成正确")


def test_memory_cache():
    """测试内存缓存"""
    print("测试内存缓存...")

    # 清空缓存
    analysis_cache.clear_memory_cache()

    # 写入缓存
    result = {"code": "600000", "score": 4.5}
    cache_key = analysis_cache.make_cache_key("600000", "2024-01-15")
    analysis_cache._memory_cache[cache_key] = result

    # 读取缓存
    cached = analysis_cache.get_cached_analysis("600000", "2024-01-15")
    assert cached is not None, "缓存不应为空"
    assert cached["score"] == 4.5, f"Expected score 4.5, got {cached['score']}"

    print("  ✓ 内存缓存读写正确")


def test_analysis_lock():
    """测试分析锁机制"""
    print("测试分析锁机制...")

    # 清空进行中的任务
    with analysis_cache._global_lock:
        analysis_cache._in_progress.clear()

    cache_key = analysis_cache.make_cache_key("600000", "2024-01-15")

    # 第一次获取锁
    acquired1, lock1 = analysis_cache.start_analysis(cache_key)
    assert acquired1 is True, "第一次获取锁应该成功"

    # 第二次获取锁
    acquired2, lock2 = analysis_cache.start_analysis(cache_key)
    assert acquired2 is False, "第二次获取锁应该失败"

    # 释放锁
    analysis_cache.finish_analysis(cache_key, {"score": 4.5})

    # 第三次获取锁
    acquired3, lock3 = analysis_cache.start_analysis(cache_key)
    assert acquired3 is True, "释放后获取锁应该成功"

    # 清理
    analysis_cache.finish_analysis(cache_key, {"score": 4.5})

    print("  ✓ 分析锁机制正确")


def test_cache_stats():
    """测试缓存统计"""
    print("测试缓存统计...")

    # 清空缓存
    analysis_cache.clear_memory_cache()
    with analysis_cache._global_lock:
        analysis_cache._in_progress.clear()

    # 添加一些数据
    cache_key = analysis_cache.make_cache_key("600000", "2024-01-15")
    analysis_cache._memory_cache[cache_key] = {"score": 4.5}

    stats = analysis_cache.get_cache_stats()
    assert stats["memory_cache_size"] == 1, f"Expected memory_cache_size=1, got {stats['memory_cache_size']}"
    assert stats["in_progress_count"] == 0, f"Expected in_progress_count=0, got {stats['in_progress_count']}"

    print("  ✓ 缓存统计正确")


def main():
    """主测试函数"""
    print("=" * 60)
    print("分析缓存服务集成验证")
    print("=" * 60)

    try:
        test_cache_key_generation()
        test_memory_cache()
        test_analysis_lock()
        test_cache_stats()

        print("=" * 60)
        print("所有测试通过!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

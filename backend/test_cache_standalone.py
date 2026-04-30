#!/usr/bin/env python3
"""
缓存服务独立验证脚本

不依赖外部包，仅验证缓存服务核心逻辑。
"""
import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from threading import Lock
from datetime import date


# 复制核心缓存服务逻辑
class AnalysisCacheService:
    """分析缓存服务"""

    STRATEGY_VERSION = "v1"

    def __init__(self):
        self._in_progress: Dict[str, Lock] = {}
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._global_lock = Lock()

    @staticmethod
    def make_cache_key(code: str, trade_date: str, strategy_version: str = None) -> str:
        version = strategy_version or AnalysisCacheService.STRATEGY_VERSION
        return f"{code}_{trade_date}_{version}"

    @staticmethod
    def make_watchlist_cache_key(watchlist_id: int, trade_date: str) -> str:
        return f"watchlist_{watchlist_id}_{trade_date}"

    def get_cached_analysis(self, code: str, trade_date: str) -> Optional[Dict[str, Any]]:
        cache_key = self.make_cache_key(code, trade_date)
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]
        return None

    def is_analysis_in_progress(self, cache_key: str) -> bool:
        with self._global_lock:
            return cache_key in self._in_progress

    def start_analysis(self, cache_key: str) -> Tuple[bool, Optional[Lock]]:
        with self._global_lock:
            if cache_key in self._in_progress:
                return False, None
            lock = Lock()
            lock.acquire()
            self._in_progress[cache_key] = lock
            return True, lock

    def finish_analysis(self, cache_key: str, result: Dict[str, Any]) -> None:
        self._memory_cache[cache_key] = result
        with self._global_lock:
            if cache_key in self._in_progress:
                lock = self._in_progress.pop(cache_key)
                if lock:
                    try:
                        lock.release()
                    except RuntimeError:
                        pass

    def clear_memory_cache(self) -> None:
        self._memory_cache.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            "memory_cache_size": len(self._memory_cache),
            "in_progress_count": len(self._in_progress),
            "in_progress_keys": list(self._in_progress.keys()),
        }


# 全局实例
analysis_cache = AnalysisCacheService()


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

    analysis_cache.clear_memory_cache()

    result = {"code": "600000", "score": 4.5}
    cache_key = analysis_cache.make_cache_key("600000", "2024-01-15")
    analysis_cache._memory_cache[cache_key] = result

    cached = analysis_cache.get_cached_analysis("600000", "2024-01-15")
    assert cached is not None, "缓存不应为空"
    assert cached["score"] == 4.5, f"Expected score 4.5, got {cached['score']}"

    print("  ✓ 内存缓存读写正确")


def test_analysis_lock():
    """测试分析锁机制"""
    print("测试分析锁机制...")

    with analysis_cache._global_lock:
        analysis_cache._in_progress.clear()

    cache_key = analysis_cache.make_cache_key("600000", "2024-01-15")

    acquired1, lock1 = analysis_cache.start_analysis(cache_key)
    assert acquired1 is True, "第一次获取锁应该成功"

    acquired2, lock2 = analysis_cache.start_analysis(cache_key)
    assert acquired2 is False, "第二次获取锁应该失败"

    analysis_cache.finish_analysis(cache_key, {"score": 4.5})

    acquired3, lock3 = analysis_cache.start_analysis(cache_key)
    assert acquired3 is True, "释放后获取锁应该成功"

    analysis_cache.finish_analysis(cache_key, {"score": 4.5})

    print("  ✓ 分析锁机制正确")


def test_cache_stats():
    """测试缓存统计"""
    print("测试缓存统计...")

    analysis_cache.clear_memory_cache()
    with analysis_cache._global_lock:
        analysis_cache._in_progress.clear()

    cache_key = analysis_cache.make_cache_key("600000", "2024-01-15")
    analysis_cache._memory_cache[cache_key] = {"score": 4.5}

    stats = analysis_cache.get_cache_stats()
    assert stats["memory_cache_size"] == 1, f"Expected memory_cache_size=1, got {stats['memory_cache_size']}"
    assert stats["in_progress_count"] == 0, f"Expected in_progress_count=0, got {stats['in_progress_count']}"

    print("  ✓ 缓存统计正确")


def test_watchlist_diagnosis_reuse():
    """测试观察列表复用单股诊断结果"""
    print("测试观察列表复用单股诊断结果...")

    analysis_cache.clear_memory_cache()

    # 模拟单股诊断结果
    code = "600000"
    trade_date = "2024-01-15"
    cache_key = analysis_cache.make_cache_key(code, trade_date)

    diagnosis_result = {
        "code": code,
        "total_score": 4.5,
        "verdict": "PASS",
        "close_price": 10.5,
    }
    analysis_cache._memory_cache[cache_key] = diagnosis_result

    # 观察列表应能获取到该结果
    cached = analysis_cache.get_cached_analysis(code, trade_date)

    assert cached is not None, "应能获取到缓存结果"
    assert cached["total_score"] == 4.5, f"Expected score 4.5, got {cached['total_score']}"

    print("  ✓ 观察列表可复用单股诊断结果")


def test_concurrent_protection():
    """测试并发保护"""
    print("测试并发保护...")

    analysis_cache.clear_memory_cache()
    with analysis_cache._global_lock:
        analysis_cache._in_progress.clear()

    code = "600000"
    trade_date = "2024-01-15"
    cache_key = analysis_cache.make_cache_key(code, trade_date)

    # 第一个请求获取锁
    acquired1, _ = analysis_cache.start_analysis(cache_key)
    assert acquired1 is True, "第一个请求应该成功"

    # 多个后续请求被拒绝
    acquired2, _ = analysis_cache.start_analysis(cache_key)
    acquired3, _ = analysis_cache.start_analysis(cache_key)
    assert acquired2 is False, "第二个请求应该失败"
    assert acquired3 is False, "第三个请求应该失败"

    # 完成后可重新获取
    analysis_cache.finish_analysis(cache_key, {"code": code})
    acquired4, _ = analysis_cache.start_analysis(cache_key)
    assert acquired4 is True, "完成后应能重新获取锁"

    analysis_cache.finish_analysis(cache_key, {"code": code})

    print("  ✓ 并发保护机制正确")


def main():
    print("=" * 60)
    print("分析缓存服务独立验证")
    print("=" * 60)

    try:
        test_cache_key_generation()
        test_memory_cache()
        test_analysis_lock()
        test_cache_stats()
        test_watchlist_diagnosis_reuse()
        test_concurrent_protection()

        print("=" * 60)
        print("所有测试通过!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

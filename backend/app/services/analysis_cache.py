"""
Analysis Cache Service
~~~~~~~~~~~~~~~~~~~~~~
分析结果缓存与去重服务

防止同一股票同一交易日被重复分析，支持：
1. 检查已有分析结果
2. 分析请求去重（防止并发重复计算）
3. 观察列表与单股诊断结果复用
"""
import asyncio
import json
import hashlib
from datetime import date
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from threading import Lock

from app.config import settings

ROOT = Path(__file__).parent.parent.parent.parent


class AnalysisCacheService:
    """分析缓存服务"""

    # 策略版本，用于缓存失效
    STRATEGY_VERSION = "v1"

    def __init__(self):
        # 正在进行的分析任务 {cache_key: Lock}
        self._in_progress: Dict[str, Lock] = {}
        # 分析结果内存缓存 {cache_key: result}
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        # 全局锁（用于修改 _in_progress 字典）
        self._global_lock = Lock()

    @staticmethod
    def make_cache_key(code: str, trade_date: str, strategy_version: str = None) -> str:
        """
        生成分析缓存键

        Args:
            code: 股票代码
            trade_date: 交易日期 (YYYY-MM-DD)
            strategy_version: 策略版本，默认使用当前版本

        Returns:
            缓存键字符串
        """
        version = strategy_version or AnalysisCacheService.STRATEGY_VERSION
        return f"{code}_{trade_date}_{version}"

    @staticmethod
    def make_watchlist_cache_key(watchlist_id: int, trade_date: str) -> str:
        """
        生成观察列表分析缓存键

        Args:
            watchlist_id: 观察列表项ID
            trade_date: 交易日期

        Returns:
            缓存键字符串
        """
        return f"watchlist_{watchlist_id}_{trade_date}"

    def get_cached_analysis(
        self,
        code: str,
        trade_date: str,
    ) -> Optional[Dict[str, Any]]:
        """
        获取已缓存的分析结果

        优先从内存缓存读取，其次从文件系统读取。

        Args:
            code: 股票代码
            trade_date: 交易日期 (YYYY-MM-DD)

        Returns:
            缓存的分析结果，如果不存在则返回 None
        """
        cache_key = self.make_cache_key(code, trade_date)

        # 1. 检查内存缓存
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        # 2. 检查文件缓存
        review_dir = ROOT / settings.review_dir
        stock_file = review_dir / trade_date / f"{code}.json"

        if stock_file.exists():
            try:
                with open(stock_file, "r", encoding="utf-8") as f:
                    result = json.load(f)

                # 写入内存缓存
                self._memory_cache[cache_key] = result
                return result
            except (json.JSONDecodeError, IOError):
                return None

        return None

    def get_watchlist_analysis(
        self,
        watchlist_id: int,
        code: str,
        trade_date: str,
    ) -> Optional[Dict[str, Any]]:
        """
        获取观察列表的分析结果（可复用单股诊断结果）

        Args:
            watchlist_id: 观察列表项ID
            code: 股票代码
            trade_date: 交易日期

        Returns:
            分析结果，如果不存在则返回 None
        """
        # 观察列表分析可以复用单股分析结果
        # 首先检查是否已有该股票该日的分析结果
        cached = self.get_cached_analysis(code, trade_date)
        if cached:
            return cached

        # 检查是否有观察列表特定的缓存
        cache_key = self.make_watchlist_cache_key(watchlist_id, trade_date)
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        return None

    def is_analysis_in_progress(self, cache_key: str) -> bool:
        """
        检查分析是否正在进行中

        Args:
            cache_key: 缓存键

        Returns:
            是否正在进行
        """
        with self._global_lock:
            return cache_key in self._in_progress

    def start_analysis(self, cache_key: str) -> Tuple[bool, Optional[Lock]]:
        """
        开始分析（获取锁）

        如果该分析已经在进行中，返回 False。
        否则创建一个新的锁并返回。

        Args:
            cache_key: 缓存键

        Returns:
            (是否成功获取锁, 锁对象)
        """
        with self._global_lock:
            if cache_key in self._in_progress:
                return False, None

            # 创建新的锁
            lock = Lock()
            lock.acquire()  # 立即获取锁
            self._in_progress[cache_key] = lock
            return True, lock

    def finish_analysis(self, cache_key: str, result: Dict[str, Any], ttl_seconds: int = 3600) -> None:
        """
        完成分析（释放锁并缓存结果）

        Args:
            cache_key: 缓存键
            result: 分析结果
            ttl_seconds: 内存缓存过期时间（秒）
        """
        # 写入内存缓存
        self._memory_cache[cache_key] = result

        with self._global_lock:
            # 释放并移除锁
            if cache_key in self._in_progress:
                lock = self._in_progress.pop(cache_key)
                if lock:
                    try:
                        lock.release()
                    except RuntimeError:
                        # 锁已经被释放
                        pass

    def save_analysis_result(
        self,
        code: str,
        trade_date: str,
        result: Dict[str, Any],
    ) -> None:
        """
        保存分析结果到文件

        Args:
            code: 股票代码
            trade_date: 交易日期
            result: 分析结果
        """
        review_dir = ROOT / settings.review_dir / trade_date
        review_dir.mkdir(parents=True, exist_ok=True)

        stock_file = review_dir / f"{code}.json"

        # 补充必要字段
        save_data = {
            "code": code,
            "analysis_date": trade_date,
            "pick_date": trade_date,
            **result
        }

        with open(stock_file, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        # 同时更新内存缓存
        cache_key = self.make_cache_key(code, trade_date)
        self._memory_cache[cache_key] = save_data

    def invalidate_cache(self, code: str, trade_date: str = None) -> None:
        """
        失效缓存

        Args:
            code: 股票代码
            trade_date: 交易日期，如果为 None 则失效该股票的所有缓存
        """
        if trade_date:
            cache_key = self.make_cache_key(code, trade_date)
            self._memory_cache.pop(cache_key, None)
        else:
            # 删除该股票的所有缓存
            keys_to_remove = [
                k for k in self._memory_cache.keys()
                if k.startswith(f"{code}_")
            ]
            for key in keys_to_remove:
                self._memory_cache.pop(key, None)

    def clear_memory_cache(self) -> None:
        """清空内存缓存"""
        self._memory_cache.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            统计信息字典
        """
        return {
            "memory_cache_size": len(self._memory_cache),
            "in_progress_count": len(self._in_progress),
            "in_progress_keys": list(self._in_progress.keys()),
        }


# 全局实例
analysis_cache = AnalysisCacheService()

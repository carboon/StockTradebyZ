"""
Analysis Cache Service Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
分析缓存服务测试用例

测试分析结果的缓存和去重功能：
- 缓存键生成
- 结果缓存读取
- 分析去重锁机制
- 观察列表与单股诊断结果复用
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.analysis_cache import analysis_cache, AnalysisCacheService


@pytest.fixture
def cache_service():
    """
    缓存服务fixture

    每次测试前清空缓存，确保测试隔离。
    """
    # 清空缓存
    analysis_cache.clear_memory_cache()
    # 清空进行中的任务
    with analysis_cache._global_lock:
        analysis_cache._in_progress.clear()
    return analysis_cache


# ============================================
# 缓存键生成测试
# ============================================

@pytest.mark.service
def test_make_cache_key_basic(cache_service):
    """
    测试基本缓存键生成
    """
    key = cache_service.make_cache_key("600000", "2024-01-15")
    assert key == "600000_2024-01-15_v1"


@pytest.mark.service
def test_make_cache_key_with_custom_version(cache_service):
    """
    测试带自定义版本的缓存键生成
    """
    key = cache_service.make_cache_key("600000", "2024-01-15", "v2")
    assert key == "600000_2024-01-15_v2"


@pytest.mark.service
def test_watchlist_cache_key(cache_service):
    """
    测试观察列表缓存键生成
    """
    key = cache_service.make_watchlist_cache_key(123, "2024-01-15")
    assert key == "watchlist_123_2024-01-15"


# ============================================
# 缓存读写测试
# ============================================

@pytest.mark.service
def test_memory_cache_write_and_read(cache_service):
    """
    测试内存缓存写入和读取
    """
    code = "600000"
    trade_date = "2024-01-15"
    result = {
        "code": code,
        "score": 4.5,
        "verdict": "PASS",
        "close_price": 10.5,
    }

    # 写入缓存
    cache_key = cache_service.make_cache_key(code, trade_date)
    cache_service._memory_cache[cache_key] = result

    # 读取缓存
    cached = cache_service.get_cached_analysis(code, trade_date)

    assert cached is not None
    assert cached["code"] == code
    assert cached["score"] == 4.5
    assert cached["verdict"] == "PASS"


@pytest.mark.service
def test_file_cache_read(cache_service, tmp_path):
    """
    测试从文件读取缓存
    """
    code = "600000"
    trade_date = "2024-01-15"

    # 创建测试文件
    test_root = tmp_path / "test_file_cache"
    review_dir = test_root / "review" / trade_date
    review_dir.mkdir(parents=True, exist_ok=True)

    result_data = {
        "code": code,
        "total_score": 4.5,
        "verdict": "PASS",
        "signal_type": "trend_start",
        "comment": "技术形态良好",
        "b1_passed": True,
        "kdj_j": 12.3,
        "close_price": 10.5,
        "analysis_date": trade_date,
        "pick_date": trade_date,
    }

    with open(review_dir / f"{code}.json", "w", encoding="utf-8") as f:
        json.dump(result_data, f)

    # Mock settings
    with patch("app.services.analysis_cache.settings") as mock_settings:
        with patch("app.services.analysis_cache.ROOT", test_root):
            mock_settings.review_dir = test_root / "review"

            # 读取缓存
            cached = cache_service.get_cached_analysis(code, trade_date)

            assert cached is not None
            assert cached["code"] == code
            assert cached["total_score"] == 4.5
            assert cached["verdict"] == "PASS"

            # 验证已写入内存缓存
            cache_key = cache_service.make_cache_key(code, trade_date)
            assert cache_key in cache_service._memory_cache


@pytest.mark.service
def test_cache_not_found(cache_service):
    """
    测试缓存不存在的情况
    """
    cached = cache_service.get_cached_analysis("999999", "2024-01-15")
    assert cached is None


# ============================================
# 分析去重测试
# ============================================

@pytest.mark.service
def test_start_analysis_success(cache_service):
    """
    测试成功获取分析锁
    """
    cache_key = cache_service.make_cache_key("600000", "2024-01-15")

    acquired, lock = cache_service.start_analysis(cache_key)

    assert acquired is True
    assert lock is not None
    assert cache_service.is_analysis_in_progress(cache_key)


@pytest.mark.service
def test_start_analysis_duplicate(cache_service):
    """
    测试重复分析请求被拒绝
    """
    cache_key = cache_service.make_cache_key("600000", "2024-01-15")

    # 第一次请求
    acquired1, lock1 = cache_service.start_analysis(cache_key)
    assert acquired1 is True

    # 第二次请求（相同缓存键）
    acquired2, lock2 = cache_service.start_analysis(cache_key)
    assert acquired2 is False
    assert lock2 is None


@pytest.mark.service
def test_finish_analysis(cache_service):
    """
    测试完成分析并释放锁
    """
    code = "600000"
    trade_date = "2024-01-15"
    cache_key = cache_service.make_cache_key(code, trade_date)

    # 开始分析
    acquired, lock = cache_service.start_analysis(cache_key)
    assert acquired is True

    # 完成分析
    result = {"code": code, "score": 4.5}
    cache_service.finish_analysis(cache_key, result)

    # 验证锁已释放
    assert not cache_service.is_analysis_in_progress(cache_key)

    # 验证结果已缓存
    cached = cache_service.get_cached_analysis(code, trade_date)
    assert cached is not None
    assert cached["score"] == 4.5


@pytest.mark.service
def test_concurrent_analysis_protection(cache_service):
    """
    测试并发分析保护机制

    模拟多个请求同时分析同一股票的情况。
    """
    code = "600000"
    trade_date = "2024-01-15"
    cache_key = cache_service.make_cache_key(code, trade_date)

    # 第一个请求获取锁
    acquired1, _ = cache_service.start_analysis(cache_key)
    assert acquired1 is True

    # 后续请求被拒绝
    acquired2, _ = cache_service.start_analysis(cache_key)
    assert acquired2 is False

    acquired3, _ = cache_service.start_analysis(cache_key)
    assert acquired3 is False

    # 释放后可以重新获取
    cache_service.finish_analysis(cache_key, {"code": code})
    acquired4, _ = cache_service.start_analysis(cache_key)
    assert acquired4 is True


# ============================================
# 结果保存测试
# ============================================

@pytest.mark.service
def test_save_analysis_result(cache_service, tmp_path):
    """
    测试保存分析结果到文件
    """
    test_root = tmp_path / "test_save_result"
    code = "600000"
    trade_date = "2024-01-15"

    with patch("app.services.analysis_cache.settings") as mock_settings:
        with patch("app.services.analysis_cache.ROOT", test_root):
            mock_settings.review_dir = test_root / "review"

            result = {
                "code": code,
                "total_score": 4.5,
                "verdict": "PASS",
                "signal_type": "trend_start",
                "comment": "良好",
            }

            cache_service.save_analysis_result(code, trade_date, result)

            # 验证文件已创建
            review_dir = test_root / "review" / trade_date
            file_path = review_dir / f"{code}.json"
            assert file_path.exists()

            # 验证文件内容
            with open(file_path, "r", encoding="utf-8") as f:
                saved = json.load(f)

            assert saved["code"] == code
            assert saved["total_score"] == 4.5
            assert saved["analysis_date"] == trade_date

            # 验证已写入内存缓存
            cache_key = cache_service.make_cache_key(code, trade_date)
            assert cache_key in cache_service._memory_cache


@pytest.mark.service
def test_save_analysis_result_single_scope_uses_isolated_directory(cache_service, tmp_path):
    test_root = tmp_path / "test_save_single_scope"
    code = "600000"
    trade_date = "2024-01-15"

    with patch("app.services.analysis_cache.settings") as mock_settings:
        with patch("app.services.analysis_cache.ROOT", test_root):
            mock_settings.review_dir = test_root / "review"

            result = {
                "code": code,
                "total_score": 4.8,
                "verdict": "PASS",
                "signal_type": "trend_start",
            }

            cache_service.save_analysis_result(code, trade_date, result, storage_scope="single")

            single_file = test_root / "review" / "single" / trade_date / f"{code}.json"
            review_file = test_root / "review" / trade_date / f"{code}.json"

            assert single_file.exists()
            assert not review_file.exists()

            cache_service.clear_memory_cache()
            cached = cache_service.get_cached_analysis(code, trade_date)

            assert cached is not None
            assert cached["code"] == code
            assert cached["total_score"] == 4.8


# ============================================
# 观察列表复用测试
# ============================================

@pytest.mark.service
def test_watchlist_reuse_diagnosis_result(cache_service):
    """
    测试观察列表复用单股诊断结果
    """
    code = "600000"
    trade_date = "2024-01-15"
    watchlist_id = 123

    # 模拟单股诊断结果
    diagnosis_result = {
        "code": code,
        "total_score": 4.5,
        "verdict": "PASS",
        "close_price": 10.5,
    }

    cache_key = cache_service.make_cache_key(code, trade_date)
    cache_service._memory_cache[cache_key] = diagnosis_result

    # 观察列表分析应能获取到该结果
    watchlist_cached = cache_service.get_watchlist_analysis(watchlist_id, code, trade_date)

    assert watchlist_cached is not None
    assert watchlist_cached["code"] == code
    assert watchlist_cached["total_score"] == 4.5


@pytest.mark.service
def test_watchlist_cache_not_found(cache_service):
    """
    测试观察列表缓存不存在
    """
    cached = cache_service.get_watchlist_analysis(123, "999999", "2024-01-15")
    assert cached is None


# ============================================
# 缓存失效测试
# ============================================

@pytest.mark.service
def test_invalidate_specific_date(cache_service):
    """
    测试失效特定日期的缓存
    """
    code = "600000"
    date1 = "2024-01-15"
    date2 = "2024-01-16"

    # 添加两个日期的缓存
    cache_service._memory_cache[cache_service.make_cache_key(code, date1)] = {"score": 4.0}
    cache_service._memory_cache[cache_service.make_cache_key(code, date2)] = {"score": 4.5}

    # 失效第一个日期
    cache_service.invalidate_cache(code, date1)

    # 验证
    assert cache_service.make_cache_key(code, date1) not in cache_service._memory_cache
    assert cache_service.make_cache_key(code, date2) in cache_service._memory_cache


@pytest.mark.service
def test_invalidate_all_dates(cache_service):
    """
    测试失效所有日期的缓存
    """
    code = "600000"
    date1 = "2024-01-15"
    date2 = "2024-01-16"
    date3 = "2024-01-17"

    # 添加多个日期的缓存
    cache_service._memory_cache[cache_service.make_cache_key(code, date1)] = {"score": 4.0}
    cache_service._memory_cache[cache_service.make_cache_key(code, date2)] = {"score": 4.5}
    cache_service._memory_cache[cache_service.make_cache_key(code, date3)] = {"score": 4.2}

    # 失效所有日期
    cache_service.invalidate_cache(code)

    # 验证所有缓存都已清除
    assert cache_service.make_cache_key(code, date1) not in cache_service._memory_cache
    assert cache_service.make_cache_key(code, date2) not in cache_service._memory_cache
    assert cache_service.make_cache_key(code, date3) not in cache_service._memory_cache


@pytest.mark.service
def test_clear_memory_cache(cache_service):
    """
    测试清空内存缓存
    """
    # 添加一些缓存
    cache_service._memory_cache["600000_2024-01-15_v1"] = {"score": 4.0}
    cache_service._memory_cache["000001_2024-01-15_v1"] = {"score": 4.5}

    assert len(cache_service._memory_cache) == 2

    # 清空缓存
    cache_service.clear_memory_cache()

    assert len(cache_service._memory_cache) == 0


# ============================================
# 缓存统计测试
# ============================================

@pytest.mark.service
def test_get_cache_stats(cache_service):
    """
    测试获取缓存统计信息
    """
    # 添加一些数据
    cache_service._memory_cache["600000_2024-01-15_v1"] = {"score": 4.0}
    cache_key = cache_service.make_cache_key("600000", "2024-01-15")
    cache_service.start_analysis(cache_key)

    stats = cache_service.get_cache_stats()

    assert stats["memory_cache_size"] == 1
    assert stats["in_progress_count"] == 1
    assert cache_key in stats["in_progress_keys"]


# ============================================
# 边界条件测试
# ============================================

@pytest.mark.service
def test_empty_code_or_date(cache_service):
    """
    测试空代码或日期的处理
    """
    # 空字符串应该正常处理
    key1 = cache_service.make_cache_key("", "2024-01-15")
    assert key1 == "_2024-01-15_v1"

    key2 = cache_service.make_cache_key("600000", "")
    assert key2 == "600000__v1"


@pytest.mark.service
def test_special_characters_in_code(cache_service):
    """
    测试包含特殊字符的代码
    """
    # 虽然实际股票代码不会包含特殊字符，但测试健壮性
    key = cache_service.make_cache_key("600000-ABC", "2024-01-15")
    assert "600000-ABC" in key
    assert "2024-01-15" in key

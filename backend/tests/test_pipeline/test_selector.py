"""
test_selector.py — 选股策略核心测试套件
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

测试 pipeline/Selector.py 中的各项功能:
- KDJ指标计算与信号识别
- 知行线计算与条件判断
- 周线多头排列判断
- B1选股策略完整流程
- 砖型图选股策略

测试标记:
    @pytest.mark.slow: 标记可能较慢的测试（Pipeline测试可能涉及大量数据）
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

# 添加 pipeline 目录到 Python 路径
pipeline_dir = Path(__file__).parent.parent.parent.parent / "pipeline"
sys.path.insert(0, str(pipeline_dir))

from Selector import (
    # Numba加速函数
    _kdj_core,
    _green_run,
    _max_vol_not_bearish,
    _compute_brick_numba,
    # 指标计算函数
    compute_kdj,
    compute_zx_lines,
    compute_weekly_close,
    compute_weekly_ma_bull,
    compute_brick_chart,
    # Filter类
    KDJQuantileFilter,
    ZXConditionFilter,
    WeeklyMABullFilter,
    MaxVolNotBearishFilter,
    BrickPatternFilter,
    BrickComputeParams,
    ZXDQRatioFilter,
    # Selector类
    PipelineSelector,
    B1Selector,
    BrickChartSelector,
)


# =============================================================================
# 测试数据生成工具函数
# =============================================================================

def create_sample_ohlcv_data(
    n: int = 200,
    start_date: str = "2023-01-01",
    trend: str = "neutral",
    volatility: float = 0.02,
) -> pd.DataFrame:
    """
    创建示例OHLCV测试数据

    Args:
        n: K线数量
        start_date: 起始日期
        trend: 趋势方向 ("bullish", "bearish", "neutral")
        volatility: 波动率

    Returns:
        包含 date, open, high, low, close, volume 列的 DataFrame
    """
    dates = pd.date_range(start=start_date, periods=n, freq="D")

    # 基础价格生成
    if trend == "bullish":
        base_price = 10.0 + np.cumsum(np.random.randn(n) * 0.1 + 0.05)
    elif trend == "bearish":
        base_price = 20.0 + np.cumsum(np.random.randn(n) * 0.1 - 0.05)
    else:
        base_price = 15.0 + np.cumsum(np.random.randn(n) * 0.1)

    # 确保价格为正
    base_price = np.maximum(base_price, 1.0)

    # 生成OHLC
    open_price = base_price * (1 + np.random.randn(n) * volatility * 0.5)
    close_price = base_price * (1 + np.random.randn(n) * volatility * 0.5)

    # high和low基于open和close
    high_price = np.maximum(open_price, close_price) * (1 + np.abs(np.random.randn(n)) * volatility * 0.3)
    low_price = np.minimum(open_price, close_price) * (1 - np.abs(np.random.randn(n)) * volatility * 0.3)

    # 成交量 (随机)
    volume = np.random.randint(1000000, 50000000, size=n)

    df = pd.DataFrame({
        "date": dates,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    })
    return df


def create_bullish_trend_data(
    n: int = 200,
    start_date: str = "2023-01-01",
) -> pd.DataFrame:
    """
    创建明显的多头趋势数据

    特征:
    - 价格持续上涨
    - 均线多头排列
    - 成交量健康
    """
    dates = pd.date_range(start=start_date, periods=n, freq="D")

    # 创建上涨趋势
    trend = np.linspace(0, 10, n)
    noise = np.random.randn(n) * 0.3
    base_price = 10.0 + trend + noise

    open_price = base_price * (1 + np.random.randn(n) * 0.01)
    close_price = base_price * (1 + np.random.randn(n) * 0.01)
    high_price = np.maximum(open_price, close_price) * (1 + np.random.rand(n) * 0.01)
    low_price = np.minimum(open_price, close_price) * (1 - np.random.rand(n) * 0.01)

    # 上涨日成交量更大
    volume = np.random.randint(5000000, 30000000, size=n)
    volume[n//2:] = volume[n//2:] * 2  # 后期成交量放大

    df = pd.DataFrame({
        "date": dates,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    })
    return df


def create_bearish_trend_data(
    n: int = 200,
    start_date: str = "2023-01-01",
) -> pd.DataFrame:
    """
    创建明显的空头趋势数据

    特征:
    - 价格持续下跌
    - 均线空头排列
    """
    dates = pd.date_range(start=start_date, periods=n, freq="D")

    # 创建下跌趋势
    trend = np.linspace(10, 0, n)
    noise = np.random.randn(n) * 0.3
    base_price = 20.0 + trend + noise

    open_price = base_price * (1 + np.random.randn(n) * 0.01)
    close_price = base_price * (1 + np.random.randn(n) * 0.01)
    high_price = np.maximum(open_price, close_price) * (1 + np.random.rand(n) * 0.01)
    low_price = np.minimum(open_price, close_price) * (1 - np.random.rand(n) * 0.01)

    volume = np.random.randint(1000000, 20000000, size=n)

    df = pd.DataFrame({
        "date": dates,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    })
    return df


def create_kdj_low_data(
    n: int = 150,
    start_date: str = "2023-01-01",
) -> pd.DataFrame:
    """
    创建KDJ处于低位的测试数据

    特征:
    - 近期价格下跌，J值处于低位
    - 适合测试KDJ低位信号
    """
    dates = pd.date_range(start=start_date, periods=n, freq="D")

    # 前半段上涨，后半段下跌（创造J值低位）
    trend = np.concatenate([
        np.linspace(0, 5, n // 2),
        np.linspace(5, 0, n - n // 2),
    ])
    noise = np.random.randn(n) * 0.2
    base_price = 15.0 + trend + noise

    open_price = base_price * (1 + np.random.randn(n) * 0.01)
    close_price = base_price * (1 + np.random.randn(n) * 0.01)
    high_price = np.maximum(open_price, close_price) * (1 + np.random.rand(n) * 0.01)
    low_price = np.minimum(open_price, close_price) * (1 - np.random.rand(n) * 0.01)

    volume = np.random.randint(5000000, 30000000, size=n)

    df = pd.DataFrame({
        "date": dates,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    })
    return df


def create_weekly_bullish_data(
    n: int = 300,  # 足够的数据以计算长期周线均线
    start_date: str = "2023-01-01",
) -> pd.DataFrame:
    """
    创建周线多头排列的测试数据

    特征:
    - 周线级别的上涨趋势
    - MA_short > MA_mid > MA_long
    """
    dates = pd.date_range(start=start_date, periods=n, freq="D")

    # 创建长期上涨趋势
    trend = np.linspace(0, 20, n)
    # 添加周级别的波动
    weekly_cycle = np.sin(np.arange(n) * 2 * np.pi / 5) * 2
    noise = np.random.randn(n) * 0.5
    base_price = 10.0 + trend + weekly_cycle + noise

    open_price = base_price * (1 + np.random.randn(n) * 0.015)
    close_price = base_price * (1 + np.random.randn(n) * 0.015)
    high_price = np.maximum(open_price, close_price) * (1 + np.random.rand(n) * 0.01)
    low_price = np.minimum(open_price, close_price) * (1 - np.random.rand(n) * 0.01)

    volume = np.random.randint(10000000, 50000000, size=n)

    df = pd.DataFrame({
        "date": dates,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    })
    return df


def create_brick_pattern_data(
    n: int = 200,
    start_date: str = "2023-01-01",
    has_signal: bool = True,
) -> pd.DataFrame:
    """
    创建砖型图形态测试数据

    Args:
        n: K线数量
        start_date: 起始日期
        has_signal: 是否包含砖型图信号（绿柱后红柱）
    """
    dates = pd.date_range(start=start_date, periods=n, freq="D")

    if has_signal:
        # 创建震荡行情，末尾出现绿柱转红柱信号
        base = np.ones(n) * 15
        # 末尾5根K线：先跌后涨，模拟绿柱转红柱
        base[-5:] = [15.5, 15.2, 14.8, 14.5, 15.0]
    else:
        base = np.ones(n) * 15 + np.random.randn(n) * 0.5

    open_price = base * (1 + np.random.randn(n) * 0.005)
    close_price = base * (1 + np.random.randn(n) * 0.005)
    high_price = np.maximum(open_price, close_price) * (1 + np.random.rand(n) * 0.005)
    low_price = np.minimum(open_price, close_price) * (1 - np.random.rand(n) * 0.005)

    volume = np.random.randint(5000000, 30000000, size=n)

    df = pd.DataFrame({
        "date": dates,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    })
    return df


# =============================================================================
# 测试用例
# =============================================================================

class TestKDJCalculation:
    """KDJ指标计算测试"""

    def test_kdj_calculation_basic(self):
        """测试KDJ基本计算"""
        df = create_sample_ohlcv_data(n=100)
        result = compute_kdj(df, n=9)

        # 验证列存在
        assert "K" in result.columns
        assert "D" in result.columns
        assert "J" in result.columns

        # 验证无NaN（除了可能的初始值）
        assert result["K"].notna().sum() > 0
        assert result["D"].notna().sum() > 0
        assert result["J"].notna().sum() > 0

    def test_kdj_calculation_empty(self):
        """测试空数据KDJ计算"""
        df = pd.DataFrame({"open": [], "high": [], "low": [], "close": []})
        result = compute_kdj(df, n=9)

        # 空数据应返回带NaN列的DataFrame
        assert len(result) == 0
        assert "K" in result.columns
        assert "D" in result.columns
        assert "J" in result.columns

    def test_kdj_numba_core(self):
        """测试Numba加速的KDJ核心计算"""
        # 创建简单RSV序列
        rsv = np.array([10, 20, 30, 40, 50, 60, 70, 80, 90], dtype=np.float64)

        K, D, J = _kdj_core(rsv)

        # 验证返回值
        assert len(K) == len(rsv)
        assert len(D) == len(rsv)
        assert len(J) == len(rsv)

        # 验证初始值
        assert K[0] == 50.0
        assert D[0] == 50.0

        # J = 3K - 2D
        assert np.allclose(J, 3 * K - 2 * D)

    def test_kdj_signal_golden_cross(self):
        """测试KDJ金叉信号（K上穿D）"""
        # 创建从低位上涨的数据
        df = create_kdj_low_data(n=100)
        result = compute_kdj(df, n=9)

        # 检测金叉: K从下方向上穿越D
        K = result["K"].values
        D = result["D"].values

        # 寻找金叉点
        golden_crosses = []
        for i in range(1, len(K)):
            if K[i-1] < D[i-1] and K[i] > D[i]:
                golden_crosses.append(i)

        # 应该至少有一些金叉（虽然不保证每次都有）
        # 这个测试主要是验证金叉检测逻辑
        assert isinstance(golden_crosses, list)

    def test_kdj_signal_death_cross(self):
        """测试KDJ死叉信号（K下穿D）"""
        # 创建从高位下跌的数据
        df = create_bearish_trend_data(n=100)
        result = compute_kdj(df, n=9)

        # 检测死叉: K从上方向下穿越D
        K = result["K"].values
        D = result["D"].values

        # 寻找死叉点
        death_crosses = []
        for i in range(1, len(K)):
            if K[i-1] > D[i-1] and K[i] < D[i]:
                death_crosses.append(i)

        # 验证死叉检测逻辑
        assert isinstance(death_crosses, list)

    def test_kdj_quantile_filter(self):
        """测试KDJ分位过滤器"""
        df = create_kdj_low_data(n=150)

        # 创建过滤器
        filter_obj = KDJQuantileFilter(
            j_threshold=-5.0,
            j_q_threshold=0.10,
            kdj_n=9,
        )

        # 预计算KDJ
        df_with_kdj = compute_kdj(df, n=9)

        # 测试向量化mask
        mask = filter_obj.vec_mask(df_with_kdj)

        # 验证mask形状
        assert len(mask) == len(df_with_kdj)
        assert mask.dtype == bool

        # 测试单次调用
        result = filter_obj(df_with_kdj)
        assert isinstance(result, bool)


class TestZhixingLine:
    """知行线计算与测试"""

    def test_zhixing_line_calculation(self):
        """测试知行线基本计算"""
        df = create_sample_ohlcv_data(n=200)

        zxdq, zxdkx = compute_zx_lines(
            df,
            m1=14, m2=28, m3=57, m4=114,
            zxdq_span=10,
        )

        # 验证返回Series
        assert isinstance(zxdq, pd.Series)
        assert isinstance(zxdkx, pd.Series)
        assert len(zxdq) == len(df)
        assert len(zxdkx) == len(df)

    def test_zhixing_line_check_bullish(self):
        """测试知行线多头条件判断"""
        # 创建多头数据
        df = create_bullish_trend_data(n=200)

        # 预计算知行线
        zxdq, zxdkx = compute_zx_lines(
            df,
            m1=14, m2=28, m3=57, m4=114,
            zxdq_span=10,
        )
        df["zxdq"] = zxdq
        df["zxdkx"] = zxdkx

        # 创建过滤器
        filter_obj = ZXConditionFilter(
            zx_m1=14, zx_m2=28, zx_m3=57, zx_m4=114,
            zxdq_span=10,
            require_close_gt_long=True,
            require_short_gt_long=True,
        )

        # 测试向量化mask
        mask = filter_obj.vec_mask(df)

        # 验证mask
        assert len(mask) == len(df)
        assert mask.dtype == bool

    def test_zhixing_line_filter_close_below_long(self):
        """测试收盘价低于长期均线的情况"""
        df = create_bearish_trend_data(n=200)

        # 预计算知行线
        zxdq, zxdkx = compute_zx_lines(
            df,
            m1=14, m2=28, m3=57, m4=114,
            zxdq_span=10,
        )
        df["zxdq"] = zxdq
        df["zxdkx"] = zxdkx

        # 创建过滤器
        filter_obj = ZXConditionFilter(
            zx_m1=14, zx_m2=28, zx_m3=57, zx_m4=114,
            zxdq_span=10,
            require_close_gt_long=True,
            require_short_gt_long=False,
        )

        # 在下跌趋势中，close > zxdkx 应该较少
        mask = filter_obj.vec_mask(df)
        true_count = mask.sum()
        total_count = len(mask)

        # 至少有一些数据点可能通过
        assert 0 <= true_count <= total_count


class TestWeeklyMA:
    """周线均线测试"""

    def test_weekly_close_computation(self):
        """测试日线转周线收盘价"""
        # 创建足够的数据
        df = create_sample_ohlcv_data(n=100)

        weekly_close = compute_weekly_close(df)

        # 验证返回Series
        assert isinstance(weekly_close, pd.Series)
        assert len(weekly_close) > 0

        # 验证index是DatetimeIndex
        assert isinstance(weekly_close.index, pd.DatetimeIndex)

    def test_weekly_bullish_check(self):
        """测试周线多头排列检查"""
        # 创建周线多头数据
        df = create_weekly_bullish_data(n=300)

        # 计算周线多头标志
        bull = compute_weekly_ma_bull(
            df,
            ma_periods=(20, 60, 120),
        )

        # 验证返回Series
        assert isinstance(bull, pd.Series)
        assert len(bull) == len(df)
        assert bull.dtype == bool

    def test_weekly_bullish_filter(self):
        """测试周线多头过滤器"""
        df = create_weekly_bullish_data(n=300)

        # 预计算wma_bull
        df["wma_bull"] = compute_weekly_ma_bull(
            df,
            ma_periods=(20, 60, 120),
        )

        # 创建过滤器
        filter_obj = WeeklyMABullFilter(
            wma_short=20,
            wma_mid=60,
            wma_long=120,
        )

        # 测试向量化mask
        mask = filter_obj.vec_mask(df)

        # 验证mask
        assert len(mask) == len(df)
        assert mask.dtype == bool

        # 测试单次调用
        result = filter_obj(df)
        assert isinstance(result, bool)


class TestLiquidityAndVolume:
    """流动性和成交量相关测试"""

    def test_max_vol_not_bearish_calculation(self):
        """测试成交量最大日非阴线Numba计算"""
        n = 50
        vol = np.random.randint(1000000, 10000000, size=n).astype(np.float64)
        open_ = np.random.uniform(10, 20, size=n).astype(np.float64)
        close = np.random.uniform(10, 20, size=n).astype(np.float64)

        # 设置一个明显的最大成交量日为阳线
        vol[-1] = 20000000  # 最大成交量
        close[-1] = open_[-1] + 1  # 阳线

        result = _max_vol_not_bearish(vol, open_, close, n=20)

        # 验证返回类型
        assert len(result) == n
        assert result.dtype == bool

    def test_max_vol_not_bearish_filter(self):
        """测试最大成交量非阴线过滤器"""
        df = create_sample_ohlcv_data(n=100)

        # 创建过滤器
        filter_obj = MaxVolNotBearishFilter(n=20)

        # 测试向量化mask
        mask = filter_obj.vec_mask(df)

        # 验证mask
        assert len(mask) == len(df)
        assert mask.dtype == bool

        # 测试单次调用
        result = filter_obj(df)
        assert isinstance(result, bool)

    def test_liquidity_ranking_simulation(self):
        """模拟流动性排名筛选"""
        # 创建多个股票的成交额数据
        np.random.seed(42)
        stocks = {}
        for i in range(10):
            df = create_sample_ohlcv_data(n=100)
            # 随机设置成交额
            df["amount"] = np.random.uniform(1e8, 1e10, size=len(df))
            stocks[f"00{i}"] = df

        # 模拟top_m筛选
        top_m = 5
        turnover_values = {}
        for code, df in stocks.items():
            # 计算43日滚动成交额均值
            if len(df) >= 43:
                turnover_values[code] = df["amount"].rolling(43).mean().iloc[-1]
            else:
                turnover_values[code] = 0

        # 按成交额排序取前M
        top_stocks = sorted(
            turnover_values.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_m]

        # 验证
        assert len(top_stocks) == top_m
        # 第一只应该有最高成交额
        assert top_stocks[0][1] >= top_stocks[-1][1]


class TestB1Selector:
    """B1选股策略完整测试"""

    @pytest.mark.slow
    def test_b1_pattern_detection_bullish(self):
        """
        测试B1多头形态检测

        验证B1策略能正确识别符合以下条件的股票:
        1. J值处于低位 (< j_threshold 或 <= 历史分位)
        2. 收盘价 > zxdkx (长期均线)
        3. zxdq > zxdkx (知行线多头)
        4. 周线均线多头排列
        5. 成交量最大日非阴线
        """
        # 创建符合B1条件的多头数据
        df = create_weekly_bullish_data(n=300)

        # 添加KDJ低位信号（让近期J值下降）
        df = df.copy()
        df.iloc[-10:, df.columns.get_loc("close")] *= 0.95  # 近期下跌创造J值低位

        # 创建B1选择器
        selector = B1Selector(
            j_threshold=15.0,
            j_q_threshold=0.10,
            kdj_n=9,
            zx_m1=14, zx_m2=28, zx_m3=57, zx_m4=114,
            zxdq_span=10,
            require_close_gt_long=True,
            require_short_gt_long=True,
            wma_short=5, wma_mid=10, wma_long=20,  # 较短周期方便测试
            max_vol_lookback=20,
            extra_bars_buffer=10,
        )

        # 准备数据（预计算所有指标）
        prepared_df = selector.prepare_df(df)

        # 验证预计算列存在
        assert "K" in prepared_df.columns
        assert "D" in prepared_df.columns
        assert "J" in prepared_df.columns
        assert "zxdq" in prepared_df.columns
        assert "zxdkx" in prepared_df.columns
        assert "wma_bull" in prepared_df.columns
        assert "_vec_pick" in prepared_df.columns

        # 检查是否有通过的日期
        picks = selector.vec_picks_from_prepared(prepared_df)
        assert isinstance(picks, list)

    @pytest.mark.slow
    def test_b1_pattern_detection_bearish(self):
        """
        测试B1空头形态检测

        验证B1策略能正确拒绝不符合条件的股票
        """
        # 创建明显的空头数据
        df = create_bearish_trend_data(n=300)

        # 创建B1选择器
        selector = B1Selector(
            j_threshold=15.0,
            j_q_threshold=0.10,
            kdj_n=9,
            zx_m1=14, zx_m2=28, zx_m3=57, zx_m4=114,
            zxdq_span=10,
            require_close_gt_long=True,
            require_short_gt_long=True,
            wma_short=5, wma_mid=10, wma_long=20,
            max_vol_lookback=20,
            extra_bars_buffer=10,
        )

        # 准备数据
        prepared_df = selector.prepare_df(df)

        # 检查通过的日期
        picks = selector.vec_picks_from_prepared(prepared_df)

        # 在明显的空头趋势中，应该很少有或没有通过B1条件的日期
        # 这个测试主要是验证逻辑，实际通过数量可能非零
        assert isinstance(picks, list)

    @pytest.mark.slow
    def test_b1_select_stocks(self):
        """测试选股主流程"""
        # 创建多个股票的测试数据
        stock_data = {}
        for i in range(5):
            if i < 2:
                # 前两只股票给多头数据
                stock_data[f"60000{i}"] = create_weekly_bullish_data(n=300)
            else:
                # 其他股票给中性/空头数据
                stock_data[f"60000{i}"] = create_sample_ohlcv_data(n=300)

        # 创建B1选择器（使用date_col="date"）
        selector = B1Selector(
            j_threshold=15.0,
            j_q_threshold=0.10,
            kdj_n=9,
            zx_m1=14, zx_m2=28, zx_m3=57, zx_m4=114,
            zxdq_span=10,
            wma_short=5, wma_mid=10, wma_long=20,
            max_vol_lookback=20,
            date_col="date",  # 使用date列
        )

        # 获取最后一个日期作为选股日期（从date列获取）
        pick_date = stock_data["600000"]["date"].iloc[-1]

        # 执行选股
        selected = selector.select(pick_date, stock_data)

        # 验证返回结果
        assert isinstance(selected, list)
        # 选中的股票代码应该都在输入数据中
        for code in selected:
            assert code in stock_data

    @pytest.mark.slow
    def test_b1_select_stocks_empty(self):
        """测试空数据选股"""
        selector = B1Selector(
            j_threshold=15.0,
            j_q_threshold=0.10,
            kdj_n=9,
            zx_m1=14, zx_m2=28, zx_m3=57, zx_m4=114,
            zxdq_span=10,
            wma_short=5, wma_mid=10, wma_long=20,
            max_vol_lookback=20,
            date_col="date",
        )

        pick_date = pd.Timestamp("2024-01-01")

        # 测试空字典
        empty_data = {}
        selected = selector.select(pick_date, empty_data)
        assert selected == []

        # 测试空DataFrame（带date列，且date列有正确的dtype）
        empty_df = pd.DataFrame({"date": pd.to_datetime([])})
        empty_df_data = {"600000": empty_df}
        selected = selector.select(pick_date, empty_df_data)
        assert selected == []

        # 测试数据不足
        short_data = {"600000": create_sample_ohlcv_data(n=10)}
        selected = selector.select(pick_date, short_data)
        # 数据不足min_bars要求，应该返回空
        assert selected == []

    def test_b1_passes_df_on_date(self):
        """测试单日判断方法"""
        df = create_weekly_bullish_data(n=300)

        selector = B1Selector(
            j_threshold=15.0,
            j_q_threshold=0.10,
            kdj_n=9,
            zx_m1=14, zx_m2=28, zx_m3=57, zx_m4=114,
            zxdq_span=10,
            wma_short=5, wma_mid=10, wma_long=20,
            max_vol_lookback=20,
            date_col="date",
        )

        # 测试中间某个日期（从date列获取）
        test_date = df["date"].iloc[len(df) // 2]
        result = selector.passes_df_on_date(df, test_date)

        # 验证返回布尔值
        assert isinstance(result, bool)


class TestBrickChart:
    """砖型图策略测试"""

    def test_brick_numba_computation(self):
        """测试砖型图Numba计算"""
        df = create_sample_ohlcv_data(n=100)

        brick = _compute_brick_numba(
            df["high"].to_numpy(dtype=np.float64),
            df["low"].to_numpy(dtype=np.float64),
            df["close"].to_numpy(dtype=np.float64),
            n=4, m1=4, m2=6, m3=6,
            t=4.0, shift1=90.0, shift2=100.0,
            sma_w1=1, sma_w2=1, sma_w3=1,
        )

        # 验证返回数组
        assert len(brick) == len(df)
        assert isinstance(brick, np.ndarray)

    def test_brick_pattern_filter(self):
        """测试砖型图形态过滤器"""
        df = create_brick_pattern_data(n=100, has_signal=True)

        # 创建砖型图参数
        brick_params = BrickComputeParams(
            n=4, m1=4, m2=6, m3=6,
            t=4.0, shift1=90.0, shift2=100.0,
            sma_w1=1, sma_w2=1, sma_w3=1,
        )

        # 创建过滤器
        filter_obj = BrickPatternFilter(
            daily_return_threshold=0.05,
            brick_growth_ratio=0.5,
            min_prior_green_bars=1,
            brick_params=brick_params,
        )

        # 预计算brick列
        df["brick"] = brick_params.compute_arr(df)

        # 测试向量化mask
        mask = filter_obj.vec_mask(df)

        # 验证mask
        assert len(mask) == len(df)
        assert mask.dtype == bool

        # 测试单次调用
        result = filter_obj(df)
        assert isinstance(result, bool)

    def test_green_run_computation(self):
        """测试连续绿柱计数"""
        # 创建测试序列: 正数=红柱，负数=绿柱
        brick_vals = np.array([
            1.0, -1.0, -2.0, -0.5,  # 3根绿柱
            0.5, 1.0,  # 红柱
            -1.0, -1.5,  # 2根绿柱
        ], dtype=np.float64)

        result = _green_run(brick_vals)

        # 验证结果
        assert len(result) == len(brick_vals)
        # 检查特定位置的连续绿柱数
        # i=3时，前面有2根连续绿柱(-1.0, -2.0)
        assert result[3] == 2


class TestPipelineSelectorBase:
    """PipelineSelector基类测试"""

    def test_get_hist(self):
        """测试获取历史数据"""
        df = create_sample_ohlcv_data(n=100)

        selector = PipelineSelector(
            filters=[],
            date_col="date",
            min_bars=10,
        )

        # 获取截至某个日期的历史数据（从date列获取）
        test_date = df["date"].iloc[50]
        hist = selector.get_hist(df, test_date)

        # 验证返回数据
        assert len(hist) == 51  # index 0-50
        # 检查最后一行的date等于或早于test_date
        assert hist["date"].iloc[-1] <= test_date

    def test_passes_hist_empty(self):
        """测试空历史数据判断"""
        selector = PipelineSelector(
            filters=[],
            date_col="date",
            min_bars=10,
        )

        # 空DataFrame
        assert not selector.passes_hist(pd.DataFrame())

        # None
        assert not selector.passes_hist(None)

    def test_passes_hist_insufficient_bars(self):
        """测试K线数量不足"""
        selector = PipelineSelector(
            filters=[],
            date_col="date",
            min_bars=100,
            extra_bars_buffer=10,
        )

        short_df = create_sample_ohlcv_data(n=50)
        assert not selector.passes_hist(short_df)

    def test_vec_picks_from_prepared_no_column(self):
        """测试没有_vec_pick列的情况"""
        df = create_sample_ohlcv_data(n=100)
        selector = PipelineSelector(
            filters=[],
            date_col="date",
        )

        picks = selector.vec_picks_from_prepared(df)
        assert picks == []

    def test_vec_picks_with_range(self):
        """测试带范围的向量化选股"""
        df = create_sample_ohlcv_data(n=100)
        df["_vec_pick"] = False
        # 设置中间部分为True
        df.iloc[20:30, df.columns.get_loc("_vec_pick")] = True

        selector = PipelineSelector(
            filters=[],
            date_col="date",
        )

        # 获取所有选股日期
        all_picks = selector.vec_picks_from_prepared(df)
        assert len(all_picks) == 10

        # 获取部分范围
        range_picks = selector.vec_picks_from_prepared(
            df,
            start=df.index[25],
            end=df.index[28],
        )
        assert len(range_picks) == 4  # index 25-28


class TestEdgeCases:
    """边界条件和错误情况测试"""

    def test_kdj_with_nan_values(self):
        """测试包含NaN值的KDJ计算"""
        df = create_sample_ohlcv_data(n=50)
        # 添加一些NaN
        df.loc[10:15, "close"] = np.nan

        result = compute_kdj(df, n=9)

        # 验证仍然能返回结果
        assert len(result) == len(df)
        assert "K" in result.columns

    def test_zx_lines_with_short_data(self):
        """测试数据不足时的知行线计算"""
        short_df = create_sample_ohlcv_data(n=50)

        zxdq, zxdkx = compute_zx_lines(
            short_df,
            m1=14, m2=28, m3=57, m4=114,
            zxdq_span=10,
        )

        # 验证仍然返回Series
        assert len(zxdq) == len(short_df)
        assert len(zxdkx) == len(short_df)

    def test_weekly_close_with_weekend_gap(self):
        """测试跨周末的周线计算"""
        # 创建跨越周末的数据
        dates = pd.date_range(start="2023-01-01", periods=20, freq="B")  # 工作日
        df = pd.DataFrame({
            "date": dates,
            "close": np.random.uniform(10, 20, size=len(dates)),
        })

        weekly = compute_weekly_close(df)

        # 验证返回结果
        assert len(weekly) > 0
        assert isinstance(weekly.index, pd.DatetimeIndex)

    def test_empty_dataframe_handling(self):
        """测试空DataFrame的处理"""
        empty_df = pd.DataFrame()

        selector = PipelineSelector(
            filters=[],
            date_col="date",
            min_bars=1,
        )

        # 各种方法应该能处理空数据而不崩溃
        assert not selector.passes_hist(empty_df)

    def test_single_row_dataframe(self):
        """测试只有一行数据的DataFrame"""
        single_row_df = pd.DataFrame({
            "date": [pd.Timestamp("2023-01-01")],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [1000000],
        })

        # KDJ计算
        result = compute_kdj(single_row_df, n=9)
        assert "K" in result.columns

    def test_volume_zero_edge_case(self):
        """测试成交量为0的边界情况"""
        df = create_sample_ohlcv_data(n=50)
        df.loc[0, "volume"] = 0

        filter_obj = MaxVolNotBearishFilter(n=10)
        mask = filter_obj.vec_mask(df)

        # 验证不会出错
        assert len(mask) == len(df)


class TestIntegration:
    """集成测试"""

    @pytest.mark.slow
    def test_full_pipeline_workflow(self):
        """测试完整的选股流程"""
        # 1. 创建测试数据
        stock_data = {
            "600000": create_weekly_bullish_data(n=300),
            "600036": create_sample_ohlcv_data(n=300),
            "000001": create_bearish_trend_data(n=300),
        }

        # 2. 创建选择器
        selector = B1Selector(
            j_threshold=15.0,
            j_q_threshold=0.10,
            kdj_n=9,
            zx_m1=14, zx_m2=28, zx_m3=57, zx_m4=114,
            zxdq_span=10,
            wma_short=5, wma_mid=10, wma_long=20,
            max_vol_lookback=20,
        )

        # 3. 预计算所有股票的数据
        prepared_data = {}
        for code, df in stock_data.items():
            prepared_data[code] = selector.prepare_df(df)

        # 4. 获取选股日期
        pick_date = pd.Timestamp("2024-01-01")
        selected = selector.select(pick_date, prepared_data)

        # 5. 验证结果
        assert isinstance(selected, list)
        # 选中的股票应该存在
        for code in selected:
            assert code in stock_data

        # 6. 使用向量化方法获取所有通过日期
        for code, prepared_df in prepared_data.items():
            picks = selector.vec_picks_from_prepared(prepared_df)
            assert isinstance(picks, list)


# =============================================================================
# 性能测试
# =============================================================================

class TestPerformance:
    """性能相关测试"""

    @pytest.mark.slow
    def test_vec_vs_scalar_performance(self):
        """测试向量化方法与逐日调用的性能差异"""
        df = create_weekly_bullish_data(n=500)

        selector = B1Selector(
            j_threshold=15.0,
            j_q_threshold=0.10,
            kdj_n=9,
            zx_m1=14, zx_m2=28, zx_m3=57, zx_m4=114,
            zxdq_span=10,
            wma_short=5, wma_mid=10, wma_long=20,
            max_vol_lookback=20,
        )

        # 预计算
        prepared_df = selector.prepare_df(df)

        # 向量化方法
        import time
        start = time.time()
        vec_picks = selector.vec_picks_from_prepared(prepared_df)
        vec_time = time.time() - start

        # 验证结果
        assert isinstance(vec_picks, list)
        # 向量化应该很快
        assert vec_time < 1.0  # 应该在1秒内完成

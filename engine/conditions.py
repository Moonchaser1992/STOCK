"""选股条件：每个条件是一个独立函数，接收股票数据和K线DataFrame，返回 bool 或 float"""
from __future__ import annotations

import pandas as pd
import numpy as np


def check_listed_days(code: str, listed_date_map: dict, min_days: int = 100) -> bool:
    """检查上市天数是否满足最低要求"""
    from datetime import datetime
    if code not in listed_date_map or listed_date_map[code] is None:
        return True  # 无法获取上市日期时不排除
    days = (datetime.now() - listed_date_map[code]).days
    return days >= min_days


def check_market_cap(market_cap: float, max_cap_yi: float = 400) -> bool:
    """检查总市值是否小于上限（单位：亿元）"""
    if pd.isna(market_cap):
        return False
    return market_cap < max_cap_yi


def calc_period_return(df: pd.DataFrame, period: int) -> float | None:
    """计算 period 日累计涨跌幅"""
    if len(df) < period + 1:
        return None
    close_now = df.iloc[-1]["close"]
    close_before = df.iloc[-(period + 1)]["close"]
    if close_before <= 0:
        return None
    return (close_now - close_before) / close_before


def check_volume_price_pattern(df: pd.DataFrame, window: int = 12) -> bool:
    """
    量价形态判定（模糊实现）：
    将最近 window 天分成前后两半，前半应放量上涨，后半应缩量回调。
    返回 True 表示符合形态。
    """
    if len(df) < window:
        return False

    recent = df.tail(window).copy()
    half = window // 2

    first_half = recent.iloc[:half]
    second_half = recent.iloc[half:]

    # 均量用于对比
    first_avg_vol = first_half["volume"].mean()
    second_avg_vol = second_half["volume"].mean()

    # 前半段价格趋势（简单用：前半段均价 > 前半段起始价）
    first_price_start = first_half["close"].iloc[0]
    first_price_end = first_half["close"].iloc[-1]
    first_half_up = first_price_end > first_price_start

    # 后半段价格趋势：走平或回调（后半段末期价格 <= 后半段初期价格 * 1.02)
    second_price_start = second_half["close"].iloc[0]
    second_price_end = second_half["close"].iloc[-1]
    second_half_flat_or_down = second_price_end <= second_price_start * 1.02

    # 成交量对比：前半段均量 > 后半段均量 × 1.3
    vol_contracting = first_avg_vol > second_avg_vol * 1.3

    return first_half_up and second_half_flat_or_down and vol_contracting

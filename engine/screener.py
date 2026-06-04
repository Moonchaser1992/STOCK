"""选股筛选引擎：编排多层筛选流程，输出每日结果"""
from __future__ import annotations

import os
import pandas as pd
from datetime import datetime

from config import (
    RESULTS_DIR, RANK_TOP_N, RANK_PERIODS,
    MIN_LISTING_DAYS, MAX_MARKET_CAP_YI, VP_WINDOW_MAX, VP_WINDOW_MIN,
)
from engine.fetcher import get_all_stock_codes, fetch_all_stocks_with_kline, _get_listed_date
from engine.conditions import (
    check_listed_days, check_market_cap,
    calc_period_return, check_volume_price_pattern,
)


def run_screening(trade_date: str | None = None, sentiment: dict | None = None) -> list[dict]:
    """
    执行完整选股流程。
    trade_date: 选股基准日期，格式 YYYYMMDD，默认为最近交易日
    sentiment: 市场情绪指标，由 engine.sentiment.compute_sentiment() 返回
    返回: 入选股票列表 [{code, name, ...}, ...]
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y%m%d")

    print(f"\n{'='*50}")
    print(f"选股日期: {trade_date}")
    print(f"{'='*50}\n")

    # ---- 第0层：获取全量股票 + 基础过滤 ----
    print("[第0层] 获取全量股票列表...")
    all_stocks = get_all_stock_codes()
    print(f"  板块内股票总数: {len(all_stocks)}")

    # 获取上市日期
    print("  获取上市日期...")
    listed_date_map = {}
    codes = all_stocks["code"].tolist()
    for code in codes:
        listed_date_map[code] = _get_listed_date(code)

    # 基础过滤
    passed_layer0 = []
    for _, row in all_stocks.iterrows():
        code = row["code"]
        name = row["name"]
        mcap = row["market_cap"]

        if not check_listed_days(code, listed_date_map, MIN_LISTING_DAYS):
            continue
        if not check_market_cap(mcap, MAX_MARKET_CAP_YI):
            continue

        passed_layer0.append({"code": code, "name": name, "market_cap": mcap})

    print(f"  第0层过滤后: {len(passed_layer0)} 支")
    layer0_codes = [s["code"] for s in passed_layer0]

    # ---- 第1层：拉K线 + 涨幅排名初筛 ----
    print(f"\n[第1层] 拉取K线数据 + 涨幅排名...")
    all_kline = fetch_all_stocks_with_kline(layer0_codes)

    # 计算各周期涨幅
    ranked_stocks = {}  # code -> set of ranking keys
    for period_name, period_days in RANK_PERIODS.items():
        returns = []
        for stock in passed_layer0:
            code = stock["code"]
            if code not in all_kline:
                continue
            df = all_kline[code]
            ret = calc_period_return(df, period_days)
            if ret is not None:
                returns.append((code, stock["name"], ret))
        # 按涨幅降序排列，取前 N
        returns.sort(key=lambda x: x[2], reverse=True)
        top_n = returns[:RANK_TOP_N]
        print(f"  {period_name}涨幅 Top{RANK_TOP_N}: {len(top_n)} 支")
        for code, name, ret in top_n:
            if code not in ranked_stocks:
                ranked_stocks[code] = set()
            ranked_stocks[code].add(period_name)

    print(f"  去重后初筛股票池: {len(ranked_stocks)} 支")

    # ---- 第2层：量价形态筛选 ----
    print(f"\n[第2层] 量价形态筛选...")
    final_picks = []
    for code, rank_sources in ranked_stocks.items():
        if code not in all_kline:
            continue
        df = all_kline[code]

        # 找最佳窗口（在 VP_WINDOW_MIN 到 VP_WINDOW_MAX 之间尝试）
        best_matched = False
        for window in range(VP_WINDOW_MIN, min(VP_WINDOW_MAX + 1, len(df) + 1)):
            if check_volume_price_pattern(df, window):
                best_matched = True
                break

        if best_matched:
            stock_info = next((s for s in passed_layer0 if s["code"] == code), None)
            if stock_info:
                # 计算最近涨跌幅
                ret_1d = calc_period_return(df, 1)
                ret_5d = calc_period_return(df, 5)
                final_picks.append({
                    "code": code,
                    "name": stock_info["name"],
                    "market_cap_yi": stock_info["market_cap"],
                    "ret_1d": round(ret_1d * 100, 2) if ret_1d is not None else None,
                    "ret_5d": round(ret_5d * 100, 2) if ret_5d is not None else None,
                    "rank_sources": ",".join(sorted(rank_sources)),
                    "close": df.iloc[-1]["close"],
                    "volume": df.iloc[-1]["volume"],
                })

    print(f"  第2层过滤后: {len(final_picks)} 支")

    # ---- 保存结果 ----
    save_results(final_picks, trade_date, sentiment)
    return final_picks


def save_results(results: list[dict], trade_date: str, sentiment: dict | None = None):
    """保存筛选结果到 CSV"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    filepath = os.path.join(RESULTS_DIR, f"{trade_date}.csv")
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values("ret_1d", ascending=False, na_position="last")
        # 附加情绪标记
        if sentiment:
            df["sentiment_score"] = sentiment.get("score", "")
            df["sentiment_level"] = sentiment.get("level", "")
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    if sentiment:
        print(f"  情绪: {sentiment.get('level','')} ({sentiment.get('score','')}分)")
    print(f"\n结果已保存: {filepath}")


def load_results(trade_date: str) -> pd.DataFrame:
    """加载指定日期的筛选结果"""
    filepath = os.path.join(RESULTS_DIR, f"{trade_date}.csv")
    if os.path.exists(filepath):
        return pd.read_csv(filepath, encoding="utf-8-sig")
    return pd.DataFrame()

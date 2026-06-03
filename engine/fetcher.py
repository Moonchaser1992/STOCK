"""数据获取层：akshare 封装 + 本地缓存 + 涨停量修正"""
from __future__ import annotations
import os
import pandas as pd
from datetime import datetime
import akshare as ak

from config import (
    CACHE_DIR,
    ALLOWED_BOARD_PREFIXES,
    LIMIT_UP_RATIO_BJ,
    LIMIT_UP_RATIO_OTHER,
    LIMIT_UP_VOLUME_MIN_RATIO,
)


def _board_prefix(code: str) -> str:
    """判断股票代码属于哪个板块，返回前缀"""
    code = str(code)
    if code.startswith(("300", "301")):
        return "300"
    elif code.startswith("688"):
        return "688"
    elif code.startswith("8"):
        return "8"
    return ""


def get_all_stock_codes():
    """
    获取创业板+科创板+北交所所有股票代码和基本信息。
    返回 DataFrame: code, name, market_cap
    """
    # akshare 实时行情，包含市值等信息
    df = ak.stock_zh_a_spot_em()
    df = df.rename(columns={
        "代码": "code",
        "名称": "name",
        "总市值": "market_cap",
        "60日涨跌幅": "chg_60d",
    })

    # 过滤板块
    df = df[df["code"].apply(lambda x: any(str(x).startswith(p) for p in ALLOWED_BOARD_PREFIXES))]
    df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")

    # 过滤 ST
    df = df[~df["name"].str.contains("ST|退", na=False)]

    return df[["code", "name", "market_cap"]].copy()


def _get_listed_date(code: str) -> datetime | None:
    """获取个股上市日期（通过历史K线最早日期推断）"""
    cache_path = os.path.join(CACHE_DIR, f"{code}.csv")
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path, parse_dates=["date"])
        return df["date"].min()
    # 尝试拉取日K线
    try:
        hist = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
        if not hist.empty:
            hist["日期"] = pd.to_datetime(hist["日期"])
            return hist["日期"].min()
    except Exception:
        pass
    return None


def fetch_daily_kline(code: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    获取单支股票的日K线数据（前复权），优先读缓存。
    返回 DataFrame: date, open, high, low, close, volume, amount
    """
    cache_path = os.path.join(CACHE_DIR, f"{code}.csv")

    if not force_refresh and os.path.exists(cache_path):
        df = pd.read_csv(cache_path, parse_dates=["date"])
        # 如果缓存是今天之前的数据，增量拉取
        last_date = df["date"].max()
        if last_date.date() < datetime.now().date():
            try:
                new_data = _fetch_incremental(code, last_date)
                if new_data is not None and not new_data.empty:
                    df = pd.concat([df, new_data], ignore_index=True)
                    df = df.drop_duplicates(subset=["date"], keep="last")
                    df = df.sort_values("date")
                    df.to_csv(cache_path, index=False)
            except Exception:
                pass
        return df

    # 全量拉取
    try:
        hist = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
        if hist.empty:
            return pd.DataFrame()

        df = pd.DataFrame({
            "date": pd.to_datetime(hist["日期"]),
            "open": hist["开盘"],
            "high": hist["最高"],
            "low": hist["最低"],
            "close": hist["收盘"],
            "volume": hist["成交量"],
            "amount": hist["成交额"],
            "turnover": hist.get("换手率", 0),
        })
        df = df.sort_values("date").reset_index(drop=True)

        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        df.to_csv(cache_path, index=False)
        return df
    except Exception as e:
        print(f"[WARN] 拉取 {code} 失败: {e}")
        return pd.DataFrame()


def _fetch_incremental(code: str, last_date: datetime) -> pd.DataFrame | None:
    """增量拉取 last_date 之后的数据"""
    hist = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
    if hist.empty:
        return None
    hist["日期"] = pd.to_datetime(hist["日期"])
    new_data = hist[hist["日期"] > last_date]
    if new_data.empty:
        return None
    return pd.DataFrame({
        "date": pd.to_datetime(new_data["日期"]),
        "open": new_data["开盘"],
        "high": new_data["最高"],
        "low": new_data["最低"],
        "close": new_data["收盘"],
        "volume": new_data["成交量"],
        "amount": new_data["成交额"],
        "turnover": new_data.get("换手率", 0),
    })


def correct_limit_up_volume(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """
    修正涨停日成交量失真问题。
    若某日涨停且成交量远低于近5日均量，按涨停前日均量估算。
    """
    if df.empty or len(df) < 6:
        return df

    # 判断涨停幅度：使用 config 中的配置值
    if str(code).startswith("8"):
        limit_up_ratio = LIMIT_UP_RATIO_BJ
    else:
        limit_up_ratio = LIMIT_UP_RATIO_OTHER

    df = df.copy()
    df["is_limit_up"] = False
    df["volume_raw"] = df["volume"].copy()

    for i in range(5, len(df)):
        # 判断涨停: (close - pre_close) / pre_close >= (limit_up_ratio - 0.005)
        # 0.005 容差处理
        pre_close = df.iloc[i - 1]["close"]
        if pre_close > 0:
            chg = (df.iloc[i]["close"] - pre_close) / pre_close
            if chg >= limit_up_ratio - 0.005:
                df.at[df.index[i], "is_limit_up"] = True

    # 修正涨停日成交量
    for i in range(5, len(df)):
        if df.iloc[i]["is_limit_up"]:
            avg_vol_5d = df.iloc[i - 5:i]["volume"].mean()
            current_vol = df.iloc[i]["volume"]
            if avg_vol_5d > 0 and current_vol < avg_vol_5d * LIMIT_UP_VOLUME_MIN_RATIO:
                # 按涨停前5日均量估算（实际买盘需求至少是均量水平）
                df.at[df.index[i], "volume"] = avg_vol_5d

    return df


def fetch_all_stocks_with_kline(codes: list[str]) -> dict[str, pd.DataFrame]:
    """
    批量获取所有目标股票的K线数据（带成交量修正）。
    返回 {code: DataFrame}
    """
    result = {}
    fail_count = 0
    for i, code in enumerate(codes):
        df = fetch_daily_kline(code)
        if not df.empty:
            df = correct_limit_up_volume(df, code)
            result[code] = df
        else:
            fail_count += 1

    print(f"数据获取完成: {len(result)}/{len(codes)} 支成功, {fail_count} 支失败")
    return result

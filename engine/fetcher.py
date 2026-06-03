"""数据获取层：东方财富 API 直连 + 本地缓存 + 涨停量修正"""
from __future__ import annotations
import os
import time
import random
import pandas as pd
import requests
from datetime import datetime

from config import (
    CACHE_DIR,
    ALLOWED_BOARD_PREFIXES,
    LIMIT_UP_RATIO_BJ,
    LIMIT_UP_RATIO_OTHER,
    LIMIT_UP_VOLUME_MIN_RATIO,
)

# 东方财富 API 基础 URL
EM_SPOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def _em_request(url: str, params: dict, timeout: int = 20, max_retries: int = 3) -> dict:
    """
    直接 HTTP GET 请求东方财富 API，带重试，返回解析后的 JSON dict。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json, text/plain, */*",
    }

    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if data is None:
                raise ValueError("JSON 解析返回 None")
            return data
        except Exception as e:
            last_exc = e
            if attempt < max_retries - 1:
                delay = 1.0 * (2 ** attempt) + random.uniform(0.5, 1.5)
                time.sleep(delay)

    raise last_exc


def _get_em_market_code(code: str) -> str:
    """将股票代码转为东方财富 market 标识"""
    code_str = str(code).zfill(6)
    if code_str.startswith(("300", "301", "0", "2")):
        return f"0.{code_str}"
    elif code_str.startswith(("6", "688")):
        return f"1.{code_str}"
    elif code_str.startswith(("8", "4")):
        return f"0.{code_str}"  # 北交所
    return f"0.{code_str}"


def get_all_stock_codes():
    """
    获取创业板+科创板+北交所所有股票代码和基本信息。
    直接调东方财富 API，不依赖 akshare 的请求层。
    返回 DataFrame: code, name, market_cap
    """
    all_rows = []
    page = 1
    page_size = 500

    while True:
        params = {
            "pn": str(page),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f12",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f2,f3,f12,f14,f15,f20,f21",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        }
        data = _em_request(EM_SPOT_URL, params)
        items = data.get("data", {}).get("diff", [])
        if not items:
            break

        for item in items:
            code = item.get("f12", "")
            if any(str(code).startswith(p) for p in ALLOWED_BOARD_PREFIXES):
                all_rows.append({
                    "code": code,
                    "name": item.get("f14", ""),
                    "market_cap": item.get("f20", None),  # 总市值(元)
                })

        total = data.get("data", {}).get("total", 0)
        if page * page_size >= total:
            break
        page += 1
        time.sleep(0.3)

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("[WARN] 未获取到任何股票数据")
        return pd.DataFrame(columns=["code", "name", "market_cap"])

    # 市值单位转换：东方财富返回的是元，转为亿元
    df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")
    df["market_cap"] = df["market_cap"] / 1e8  # 元 -> 亿元

    # 过滤 ST
    df = df[~df["name"].str.contains("ST|退", na=False)]

    print(f"  获取到 {len(df)} 支股票（板内，已排除ST）")
    return df[["code", "name", "market_cap"]].copy()


def _get_listed_date(code: str) -> datetime | None:
    """获取个股上市日期（通过历史K线最早日期推断）"""
    cache_path = os.path.join(CACHE_DIR, f"{code}.csv")
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path, parse_dates=["date"])
        return df["date"].min()

    # 尝试拉取日K线
    try:
        df = _fetch_kline_raw(code)
        if not df.empty:
            return df["date"].min()
    except Exception:
        pass
    return None


def _fetch_kline_raw(code: str, days: int = 360) -> pd.DataFrame:
    """
    直接调东方财富 K线 API 获取日K线数据（前复权）。
    返回 DataFrame: date, open, high, low, close, volume, amount, turnover
    """
    market_code = _get_em_market_code(code)
    params = {
        "secid": market_code,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",        # 日K
        "fqt": "1",          # 前复权
        "end": "20500101",
        "lmt": str(days),
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    }

    data = _em_request(EM_KLINE_URL, params)
    klines = data.get("data", {}).get("klines", [])
    if not klines:
        return pd.DataFrame()

    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 8:
            continue
        rows.append({
            "date": pd.to_datetime(parts[0]),
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
            "amount": float(parts[6]),
            "turnover": float(parts[7]) if len(parts) > 7 else 0.0,
        })

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


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

    # 全量拉取（拉最近 1000 天足够覆盖近3年）
    try:
        df = _fetch_kline_raw(code, days=1000)
        if df.empty:
            return pd.DataFrame()

        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        df.to_csv(cache_path, index=False)
        return df
    except Exception as e:
        print(f"[WARN] 拉取 {code} 失败: {e}")
        return pd.DataFrame()


def _fetch_incremental(code: str, last_date: datetime) -> pd.DataFrame | None:
    """增量拉取 last_date 之后的数据"""
    df = _fetch_kline_raw(code, days=30)  # 拉最近30天足够覆盖增量
    if df.empty:
        return None
    new_data = df[df["date"] > last_date]
    if new_data.empty:
        return None
    return new_data


def correct_limit_up_volume(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """
    修正涨停日成交量失真问题。
    若某日涨停且成交量远低于近5日均量，按涨停前日均量估算。
    """
    if df.empty or len(df) < 6:
        return df

    # 判断涨停幅度
    if str(code).startswith("8"):
        limit_up_ratio = LIMIT_UP_RATIO_BJ
    else:
        limit_up_ratio = LIMIT_UP_RATIO_OTHER

    df = df.copy()
    df["is_limit_up"] = False
    df["volume_raw"] = df["volume"].copy()

    for i in range(5, len(df)):
        pre_close = df.iloc[i - 1]["close"]
        if pre_close > 0:
            chg = (df.iloc[i]["close"] - pre_close) / pre_close
            if chg >= limit_up_ratio - 0.005:
                df.at[df.index[i], "is_limit_up"] = True

    for i in range(5, len(df)):
        if df.iloc[i]["is_limit_up"]:
            avg_vol_5d = df.iloc[i - 5:i]["volume"].mean()
            current_vol = df.iloc[i]["volume"]
            if avg_vol_5d > 0 and current_vol < avg_vol_5d * LIMIT_UP_VOLUME_MIN_RATIO:
                df.at[df.index[i], "volume"] = avg_vol_5d

    return df


def fetch_all_stocks_with_kline(codes: list[str]) -> dict[str, pd.DataFrame]:
    """
    批量获取所有目标股票的K线数据（带成交量修正）。
    返回 {code: DataFrame}
    """
    result = {}
    fail_count = 0
    total = len(codes)
    for i, code in enumerate(codes):
        if (i + 1) % 50 == 0:
            print(f"  进度: {i+1}/{total}")
        df = fetch_daily_kline(code)
        if not df.empty:
            df = correct_limit_up_volume(df, code)
            result[code] = df
        else:
            fail_count += 1

    print(f"数据获取完成: {len(result)}/{total} 支成功, {fail_count} 支失败")
    return result

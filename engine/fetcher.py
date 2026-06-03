"""数据获取层：新浪 + 腾讯双源 + 本地缓存 + 涨停量修正"""
from __future__ import annotations
import os
import time
import random
import json
import re
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

# API 端点
SINA_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"


def _sina_request(url: str, params: dict, timeout: int = 20, max_retries: int = 3) -> list | dict:
    """新浪 API 请求（JSON 格式），带重试"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.sina.com.cn/",
    }
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if data is None:
                raise ValueError("JSON null")
            return data
        except Exception as e:
            last_exc = e
            if attempt < max_retries - 1:
                delay = 1.0 * (2 ** attempt) + random.uniform(0.5, 1.5)
                time.sleep(delay)
    raise last_exc


def _code_to_sina_symbol(code: str) -> str:
    """将纯数字代码转为新浪格式：sz300750, sh688001, bj920000"""
    code_str = str(code).zfill(6)
    if code_str.startswith(("300", "301", "0", "2")):
        return f"sz{code_str}"
    elif code_str.startswith(("6", "688")):
        return f"sh{code_str}"
    else:
        return f"bj{code_str}"


# ---------- 股票列表：用 akshare 新浪接口 ----------

def get_all_stock_codes():
    """
    获取创业板+科创板+北交所所有股票代码和基本信息。
    使用 akshare 的新浪数据源（不依赖东方财富 push2）。
    返回 DataFrame: code, name, market_cap
    """
    import akshare as ak

    print("  正在通过新浪获取全A股列表...")
    df = ak.stock_zh_a_spot()

    if df.empty:
        print("[WARN] 未获取到任何股票数据")
        return pd.DataFrame(columns=["code", "name", "market_cap"])

    # 新浪返回列: 代码, 名称, 最新价, 涨跌幅, 涨跌额, 买入, 卖出, 昨收, 今开, 最高, 最低, 成交量, 成交额, 时间戳
    col_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "price",
        "涨跌幅": "chg_pct",
        "成交量": "volume",
        "成交额": "amount",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 过滤板块（用交易所+数字前缀匹配，在清洗代码之前）
    # bj = 北交所, sz300/sz301 = 创业板, sh688 = 科创板
    raw_codes = df["code"].astype(str)
    mask = (
        raw_codes.str.startswith("bj") |
        raw_codes.str.match(r"sz30[01]") |
        raw_codes.str.match(r"sh688")
    )
    df = df[mask]

    # 清洗代码：去掉交易所前缀 (bj/sz/sh)
    df["code"] = raw_codes.str.replace(r"^(bj|sz|sh)", "", regex=True)

    # 过滤 ST/退市
    df = df[~df["name"].str.contains("ST|退", na=False)]

    # 新浪接口不含市值，用腾讯接口批量获取市值
    df = _enrich_market_cap(df)

    print(f"  获取到 {len(df)} 支股票（板内，已排除ST）")
    return df[["code", "name", "market_cap"]].copy()


def _enrich_market_cap(df: pd.DataFrame) -> pd.DataFrame:
    """
    用腾讯股票 API 批量获取市值数据。
    """
    codes = df["code"].tolist()
    if not codes:
        return df

    # 构建腾讯格式代码列表: sz300750, sh688001, bj830799
    qt_codes = []
    for c in codes:
        c_str = str(c).zfill(6)
        if c_str.startswith(("300", "301", "0", "2")):
            qt_codes.append(f"sz{c_str}")
        elif c_str.startswith(("6", "688")):
            qt_codes.append(f"sh{c_str}")
        else:
            qt_codes.append(f"bj{c_str}")

    # 腾讯 API 限制单次查询数量，分批 50 个
    mcap_map = {}
    batch_size = 50

    for i in range(0, len(qt_codes), batch_size):
        batch = qt_codes[i:i + batch_size]
        try:
            url = "http://qt.gtimg.cn/q=" + ",".join(batch)
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.qq.com/",
            })
            # 解析返回: v_sz300750="...数据..."
            for line in resp.text.strip().split("\n"):
                # 提取市值字段：腾讯格式中第45个分号分隔的字段是总市值(亿)
                # 实际格式: v_<code>="...~市值~..."
                match = re.search(r'v_(\w+)="([^"]*)"', line)
                if match:
                    qt_code = match.group(1)
                    fields = match.group(2).split("~")
                    # 腾讯 API 格式: 字段 [44] = 总市值(亿元), [45] = 流通市值(亿元)
                    if len(fields) > 45:
                        raw_code = qt_code[2:]  # 去掉 sz/sh/bj 前缀
                        try:
                            mcap_val = float(fields[44])
                            if mcap_val > 0:
                                mcap_map[raw_code] = mcap_val  # 已经是亿元单位
                        except (ValueError, IndexError):
                            pass
            time.sleep(0.3)
        except Exception as e:
            print(f"  [WARN] 腾讯市值API批次失败: {e}")
            time.sleep(1)

    # 合并市值
    df["market_cap"] = df["code"].map(mcap_map)
    df["market_cap"] = df["market_cap"].fillna(999999)  # 获取失败则保留（不过滤）

    hit = sum(1 for c in codes if c in mcap_map)
    print(f"  市值数据: {hit}/{len(codes)} 支获取成功")
    return df


# ---------- K线数据：用东方财富 push2his ----------

def fetch_daily_kline(code: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    获取单支股票的日K线数据（前复权），优先读缓存。
    返回 DataFrame: date, open, high, low, close, volume, amount
    """
    cache_path = os.path.join(CACHE_DIR, f"{code}.csv")

    if not force_refresh and os.path.exists(cache_path):
        df = pd.read_csv(cache_path, parse_dates=["date"])
        last_date = df["date"].max()
        if last_date.date() < datetime.now().date():
            try:
                new_data = _fetch_kline_incremental(code, last_date)
                if new_data is not None and not new_data.empty:
                    df = pd.concat([df, new_data], ignore_index=True)
                    df = df.drop_duplicates(subset=["date"], keep="last")
                    df = df.sort_values("date")
                    df.to_csv(cache_path, index=False)
            except Exception:
                pass
        return df

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


def _fetch_kline_raw(code: str, days: int = 1000) -> pd.DataFrame:
    """调新浪 API 获取日K线数据"""
    symbol = _code_to_sina_symbol(code)
    params = {
        "symbol": symbol,
        "scale": "240",       # 240 = 日K
        "ma": "no",
        "datalen": str(min(days, 2000)),  # 新浪单次最多约2000条
    }
    data = _sina_request(SINA_KLINE_URL, params)
    if not isinstance(data, list) or not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        rows.append({
            "date": pd.to_datetime(item["day"]),
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
            "volume": float(item["volume"]),
            "amount": 0.0,      # 新浪K线不含成交额
            "turnover": 0.0,     # 新浪K线不含换手率
        })
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _fetch_kline_incremental(code: str, last_date: datetime) -> pd.DataFrame | None:
    """增量拉取"""
    df = _fetch_kline_raw(code, days=30)
    if df.empty:
        return None
    new_data = df[df["date"] > last_date]
    if new_data.empty:
        return None
    return new_data


def _get_listed_date(code: str) -> datetime | None:
    """获取个股上市日期（通过K线缓存推断）"""
    cache_path = os.path.join(CACHE_DIR, f"{code}.csv")
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path, parse_dates=["date"])
        return df["date"].min()
    try:
        df = _fetch_kline_raw(code, days=1000)
        if not df.empty:
            return df["date"].min()
    except Exception:
        pass
    return None


# ---------- 涨停量修正 ----------

def correct_limit_up_volume(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """
    修正涨停日成交量失真。涨停日若无成交，用前5日均量估算。
    """
    if df.empty or len(df) < 6:
        return df

    limit_up_ratio = LIMIT_UP_RATIO_BJ if str(code).startswith("8") else LIMIT_UP_RATIO_OTHER

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
            if avg_vol_5d > 0 and df.iloc[i]["volume"] < avg_vol_5d * LIMIT_UP_VOLUME_MIN_RATIO:
                df.at[df.index[i], "volume"] = avg_vol_5d

    return df


# ---------- 批量拉取 ----------

def fetch_all_stocks_with_kline(codes: list[str]) -> dict[str, pd.DataFrame]:
    """批量获取K线数据（带成交量修正）"""
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
    print(f"  数据获取完成: {len(result)}/{total} 支成功, {fail_count} 支失败")
    return result

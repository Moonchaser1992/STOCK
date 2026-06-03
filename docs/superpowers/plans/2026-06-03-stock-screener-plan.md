# 自动化选股系统 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建每日收盘后自动筛选A股观察池的系统——创业板+科创板+北交所，涨幅排名+量价形态筛选，微信推送+本地Web复盘。

**Architecture:** Python CLI + Flask Web。核心选股引擎独立为 `engine/` 模块，akshare 获取数据，Flask 提供本地复盘页面，PushPlus 推送微信，Git 跨设备同步结果。

**Tech Stack:** Python 3.10+, akshare, pandas, Flask, mplfinance, PushPlus, Git

---

### Task 1: 项目骨架搭建

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `.gitignore`
- Create: `data/cache/.gitkeep`
- Create: `data/results/.gitkeep`

- [ ] **Step 1: 创建 requirements.txt**

```txt
akshare>=1.14.0
pandas>=2.0.0
flask>=3.0.0
mplfinance>=0.12.0
requests>=2.31.0
```

- [ ] **Step 2: 创建 .gitignore**

```gitignore
data/cache/
__pycache__/
*.pyc
.env
.env.local
```

- [ ] **Step 3: 创建 config.py**

```python
"""选股系统集中配置"""
import os

# --- 项目路径 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
RESULTS_DIR = os.path.join(DATA_DIR, "results")

# --- 市场范围 ---
# 创业板: 300xxx, 301xxx; 科创板: 688xxx; 北交所: 8xxxxx (bj前缀)
ALLOWED_BOARD_PREFIXES = ("300", "301", "688", "8")

# --- 基础过滤 ---
MAX_MARKET_CAP_YI = 400  # 总市值 < 400亿(单位:亿元)
MIN_LISTING_DAYS = 100    # 上市天数 >= 100

# --- 初筛排名 ---
RANK_TOP_N = 30  # 每种排序选前N名
RANK_PERIODS = {
    "1d": 1,
    "5d": 5,
    "10d": 10,
}

# --- 量价形态 ---
VP_WINDOW_MIN = 10  # 量价形态观察窗口最小交易日
VP_WINDOW_MAX = 15  # 量价形态观察窗口最大交易日
VP_VOLUME_RATIO = 1.3  # 前半段均量需大于后半段均量的倍数

# --- 涨停成交量修正 ---
LIMIT_UP_RATIO_BJ = 0.30   # 北交所涨停幅度
LIMIT_UP_RATIO_OTHER = 0.20  # 创业板/科创板涨停幅度
LIMIT_UP_VOLUME_MIN_RATIO = 0.6  # 涨停日量低于近5日均量的60%时触发修正

# --- 微信推送 ---
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")

# --- Git ---
GIT_AUTO_SYNC = True
```

- [ ] **Step 4: 创建占位目录**

```bash
mkdir -p data/cache data/results
touch data/cache/.gitkeep data/results/.gitkeep
```

- [ ] **Step 5: 提交**

```bash
git add requirements.txt config.py .gitignore data/
git commit -m "feat: project scaffold with config and structure"
```

---

### Task 2: 数据获取层 — engine/fetcher.py

**Files:**
- Create: `engine/__init__.py`
- Create: `engine/fetcher.py`

- [ ] **Step 1: 创建 engine 包**

```bash
touch engine/__init__.py
```

- [ ] **Step 2: 编写 fetcher.py — 获取指定板块全量日K线（带缓存）**

```python
"""数据获取层：akshare 封装 + 本地缓存 + 涨停量修正"""
import os
import pandas as pd
from datetime import datetime, timedelta
import akshare as ak

from config import CACHE_DIR, ALLOWED_BOARD_PREFIXES


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
    返回 DataFrame: code, name, market_cap, listed_date
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

    # 获取上市日期（akshare 个股信息）
    # 上市日期不在 spot 接口中，需要逐个或批量获取，这里用一个简化方式：
    # 从历史K线数据中推断——第一根K线的日期即为上市日期附近
    # 为了效率，上市日期的获取独立封装为 _get_listed_date
    return df[["code", "name", "market_cap"]].copy()


def _get_listed_date(code: str) -> datetime:
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

    # 判断涨停幅度
    if str(code).startswith("8"):
        limit_up_ratio = 0.30
    else:
        limit_up_ratio = 0.20

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
            if avg_vol_5d > 0 and current_vol < avg_vol_5d * 0.6:
                # 按涨停前5日均量 × 1.0 估算（实际买盘需求至少是均量水平）
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
```

- [ ] **Step 3: 提交**

```bash
git add engine/__init__.py engine/fetcher.py
git commit -m "feat: add data fetcher with cache and limit-up volume correction"
```

---

### Task 3: 选股条件模块 — engine/conditions.py

**Files:**
- Create: `engine/conditions.py`

- [ ] **Step 1: 编写 conditions.py**

```python
"""选股条件：每个条件是一个独立函数，接收股票数据和K线DataFrame，返回 bool 或 float"""
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

    # 计算前半段和后半段的均价与均量
    first_avg_price = first_half["close"].mean()
    first_avg_vol = first_half["volume"].mean()

    second_avg_price = second_half["close"].mean()
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
```

- [ ] **Step 2: 提交**

```bash
git add engine/conditions.py
git commit -m "feat: add screening conditions module"
```

---

### Task 4: 筛选引擎 — engine/screener.py

**Files:**
- Create: `engine/screener.py`

- [ ] **Step 1: 编写 screener.py**

```python
"""选股筛选引擎：编排多层筛选流程，输出每日结果"""
import os
import pandas as pd
from datetime import datetime
from collections import OrderedDict

from config import (
    RESULTS_DIR, RANK_TOP_N, RANK_PERIODS,
    MIN_LISTING_DAYS, MAX_MARKET_CAP_YI, VP_WINDOW_MAX, VP_WINDOW_MIN,
)
from engine.fetcher import get_all_stock_codes, fetch_all_stocks_with_kline, _get_listed_date
from engine.conditions import (
    check_listed_days, check_market_cap,
    calc_period_return, check_volume_price_pattern,
)


def run_screening(trade_date: str | None = None) -> list[dict]:
    """
    执行完整选股流程。
    trade_date: 选股基准日期，格式 YYYYMMDD，默认为最近交易日
    返回: 入选股票列表 [{code, name, reason, ...}, ...]
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
    save_results(final_picks, trade_date)
    return final_picks


def save_results(results: list[dict], trade_date: str):
    """保存筛选结果到 CSV"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    filepath = os.path.join(RESULTS_DIR, f"{trade_date}.csv")
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values("ret_1d", ascending=False, na_position="last")
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存: {filepath}")


def load_results(trade_date: str) -> pd.DataFrame:
    """加载指定日期的筛选结果"""
    filepath = os.path.join(RESULTS_DIR, f"{trade_date}.csv")
    if os.path.exists(filepath):
        return pd.read_csv(filepath, encoding="utf-8-sig")
    return pd.DataFrame()
```

- [ ] **Step 2: 提交**

```bash
git add engine/screener.py
git commit -m "feat: add screening engine with three-layer pipeline"
```

---

### Task 5: 微信推送 — notifier/wechat.py

**Files:**
- Create: `notifier/__init__.py`
- Create: `notifier/wechat.py`

- [ ] **Step 1: 创建 notifier 包**

```bash
touch notifier/__init__.py
```

- [ ] **Step 2: 编写 wechat.py**

```python
"""微信推送：通过 PushPlus 发送筛选结果到微信"""
import requests
from config import PUSHPLUS_TOKEN


PUSHPLUS_URL = "https://www.pushplus.plus/send"


def send_stock_results(results: list[dict], trade_date: str) -> bool:
    """
    推送选股结果到微信。
    results: 筛选结果列表
    trade_date: 选股日期
    返回是否推送成功
    """
    if not PUSHPLUS_TOKEN:
        print("[推送] 未配置 PUSHPLUS_TOKEN，跳过推送。")
        print("[推送] 获取方式: https://www.pushplus.plus/ 注册后获取 token")
        print("[推送] 设置方式: set PUSHPLUS_TOKEN=你的token")
        return False

    if not results:
        content = f"<h3>【{trade_date} 选股结果】</h3><p>今日无符合条件的股票。</p>"
    else:
        rows = []
        for i, s in enumerate(results, 1):
            rank = s.get("rank_sources", "")
            ret_1d = s.get("ret_1d", "-")
            row = (
                f"<tr>"
                f"<td>{i}</td>"
                f"<td>{s['code']}</td>"
                f"<td>{s['name']}</td>"
                f"<td>{ret_1d}%</td>"
                f"<td>{rank}上榜</td>"
                f"</tr>"
            )
            rows.append(row)

        content = f"""
        <h3>【{trade_date} 选股结果】</h3>
        <p>共筛选出 <b>{len(results)}</b> 支进入观察池：</p>
        <table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse;">
        <tr><th>#</th><th>代码</th><th>名称</th><th>当日涨幅</th><th>来源</th></tr>
        {''.join(rows)}
        </table>
        <p>💡 盘中关注：放量上涨即可买入</p>
        """

    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": f"选股结果 {trade_date} - {len(results)}支入选",
        "content": content,
        "template": "html",
    }

    try:
        resp = requests.post(PUSHPLUS_URL, json=payload, timeout=10)
        data = resp.json()
        if data.get("code") == 200:
            print(f"[推送] 微信推送成功")
            return True
        else:
            print(f"[推送] 推送失败: {data.get('msg', '')}")
            return False
    except Exception as e:
        print(f"[推送] 推送异常: {e}")
        return False
```

- [ ] **Step 3: 提交**

```bash
git add notifier/
git commit -m "feat: add WeChat push via PushPlus"
```

---

### Task 6: 每日入口 — run.py

**Files:**
- Create: `run.py`

- [ ] **Step 1: 编写 run.py**

```python
#!/usr/bin/env python
"""每日一键选股入口。用法: python run.py [YYYYMMDD]"""
import sys
import subprocess
from datetime import datetime

from config import GIT_AUTO_SYNC
from engine.screener import run_screening
from notifier.wechat import send_stock_results


def git_pull():
    """拉取远端最新结果"""
    try:
        subprocess.run(["git", "pull", "--no-rebase"], check=False, timeout=30)
        print("[Git] pull 完成")
    except Exception as e:
        print(f"[Git] pull 失败: {e}")


def git_push():
    """推送今日结果到远端"""
    try:
        subprocess.run(["git", "add", "data/results/"], check=False, timeout=10)
        subprocess.run(
            ["git", "commit", "-m", f"results: auto-screening {datetime.now().strftime('%Y-%m-%d')}"],
            check=False, timeout=10
        )
        subprocess.run(["git", "push"], check=False, timeout=30)
        print("[Git] push 完成")
    except Exception as e:
        print(f"[Git] push 失败: {e}")


def main():
    # 解析日期参数
    trade_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")

    print(f"\n🚀 开始选股...\n")

    # 同步远端数据
    if GIT_AUTO_SYNC:
        git_pull()

    # 执行筛选
    results = run_screening(trade_date)

    # 推送微信
    send_stock_results(results, trade_date)

    # 同步结果到远端
    if GIT_AUTO_SYNC:
        git_push()

    print(f"\n✅ 选股完成！共 {len(results)} 支进入观察池")
    print(f"复盘页面: python app.py")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 提交**

```bash
git add run.py
git commit -m "feat: add daily run entry with git sync and push"
```

---

### Task 7: Flask Web 复盘页面 — web/

**Files:**
- Create: `web/__init__.py`
- Create: `web/routes.py`
- Create: `web/templates/index.html`
- Create: `web/templates/detail.html`
- Create: `web/templates/monthly.html`
- Create: `app.py`

- [ ] **Step 1: 创建 web 包**

```bash
mkdir -p web/templates web/static
touch web/__init__.py
```

- [ ] **Step 2: 编写 web/routes.py**

```python
"""Flask 路由：复盘页面"""
import os
import pandas as pd
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify

from config import RESULTS_DIR
from engine.screener import load_results

web = Blueprint("web", __name__, template_folder="templates")


def _get_available_dates() -> list[str]:
    """获取所有有筛选结果的日期"""
    if not os.path.exists(RESULTS_DIR):
        return []
    files = [f for f in os.listdir(RESULTS_DIR) if f.endswith(".csv")]
    dates = [f.replace(".csv", "") for f in files]
    dates.sort(reverse=True)
    return dates


@web.route("/")
def index():
    """主页：日期选择 + 筛选结果表格"""
    dates = _get_available_dates()
    selected_date = request.args.get("date", dates[0] if dates else datetime.now().strftime("%Y%m%d"))

    results = load_results(selected_date)
    stocks = results.to_dict("records") if not results.empty else []

    return render_template(
        "index.html",
        dates=dates,
        selected_date=selected_date,
        stocks=stocks,
        count=len(stocks),
    )


@web.route("/detail/<code>")
def detail(code: str):
    """个股详情页"""
    date = request.args.get("date", datetime.now().strftime("%Y%m%d"))
    from engine.fetcher import fetch_daily_kline
    df = fetch_daily_kline(code)
    if df.empty:
        return render_template("detail.html", code=code, error="无法获取数据")

    # 取最近 60 个交易日的 K线图数据
    recent = df.tail(60)
    kline_data = {
        "dates": recent["date"].dt.strftime("%Y-%m-%d").tolist(),
        "close": recent["close"].tolist(),
        "volume": recent["volume"].tolist(),
    }
    return render_template("detail.html", code=code, kline=kline_data, date=date)


@web.route("/monthly")
def monthly():
    """月度统计页"""
    dates = _get_available_dates()
    monthly_stats = {}
    for d in dates:
        month_key = d[:6]  # YYYYMM
        if month_key not in monthly_stats:
            monthly_stats[month_key] = {"count": 0, "dates": 0}
        df = load_results(d)
        monthly_stats[month_key]["count"] += len(df)
        monthly_stats[month_key]["dates"] += 1

    return render_template("monthly.html", stats=monthly_stats)
```

- [ ] **Step 3: 编写 web/templates/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>选股复盘</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, 'Microsoft YaHei', sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #333; margin-bottom: 20px; }
        .nav { margin-bottom: 20px; }
        .nav a { color: #1a73e8; text-decoration: none; margin-right: 20px; }
        .date-picker { margin-bottom: 20px; }
        .date-picker select { padding: 8px 16px; font-size: 16px; }
        table { width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #fafafa; color: #555; font-weight: 600; }
        tr:hover { background: #f0f7ff; }
        .ret-up { color: #e53e3e; }
        .ret-down { color: #38a169; }
        .empty { text-align: center; padding: 60px; color: #999; }
        .summary { margin-bottom: 20px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 选股复盘</h1>
        <div class="nav">
            <a href="/">筛选结果</a>
            <a href="/monthly">月度统计</a>
        </div>

        <div class="date-picker">
            <form method="get">
                <select name="date" onchange="this.form.submit()">
                    {% for d in dates %}
                    <option value="{{ d }}" {% if d == selected_date %}selected{% endif %}>{{ d[:4] }}-{{ d[4:6] }}-{{ d[6:8] }}</option>
                    {% endfor %}
                </select>
            </form>
        </div>

        <div class="summary">📅 {{ selected_date[:4] }}-{{ selected_date[4:6] }}-{{ selected_date[6:8] }} | 共 <b>{{ count }}</b> 支入选观察池</div>

        {% if stocks %}
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>代码</th>
                    <th>名称</th>
                    <th>当日涨幅</th>
                    <th>5日涨幅</th>
                    <th>市值(亿)</th>
                    <th>排名来源</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
                {% for s in stocks %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td>{{ s.code }}</td>
                    <td>{{ s.name }}</td>
                    <td class="{% if s.ret_1d and s.ret_1d > 0 %}ret-up{% elif s.ret_1d and s.ret_1d < 0 %}ret-down{% endif %}">
                        {{ "%+.2f%%"|format(s.ret_1d) if s.ret_1d is not none else '-' }}
                    </td>
                    <td>{{ "%+.2f%%"|format(s.ret_5d) if s.ret_5d is not none else '-' }}</td>
                    <td>{{ "%.0f"|format(s.market_cap_yi) if s.market_cap_yi is not none else '-' }}</td>
                    <td>{{ s.rank_sources }}</td>
                    <td><a href="/detail/{{ s.code }}?date={{ selected_date }}">查看</a></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="empty">📭 当天无筛选结果</div>
        {% endif %}
    </div>
</body>
</html>
```

- [ ] **Step 4: 编写 web/templates/detail.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>个股详情</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, 'Microsoft YaHei', sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #333; margin-bottom: 20px; }
        .back { margin-bottom: 20px; }
        .back a { color: #1a73e8; text-decoration: none; }
        .chart-box { background: #fff; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }
        .error { text-align: center; padding: 60px; color: #e53e3e; }
    </style>
</head>
<body>
    <div class="container">
        <div class="back"><a href="/">← 返回结果列表</a></div>
        <h1>📈 {{ code }} 个股详情</h1>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% else %}
        <div class="chart-box">
            <p>K线数据已加载，近 {{ kline.dates|length }} 个交易日</p>
            <p>最新收盘价: {{ "%.2f"|format(kline.close[-1]) if kline.close else '-' }}</p>
            <!-- K线图的服务端渲染在后续迭代中添加 pyecharts/mplfinance -->
        </div>
        {% endif %}
    </div>
</body>
</html>
```

- [ ] **Step 5: 编写 web/templates/monthly.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>月度统计</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, 'Microsoft YaHei', sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #333; margin-bottom: 20px; }
        .back { margin-bottom: 20px; }
        .back a { color: #1a73e8; text-decoration: none; }
        table { width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #fafafa; color: #555; font-weight: 600; }
    </style>
</head>
<body>
    <div class="container">
        <div class="back"><a href="/">← 返回结果列表</a></div>
        <h1>📅 月度统计</h1>
        <table>
            <thead>
                <tr><th>月份</th><th>有效交易日</th><th>累计入选</th><th>日均入选</th></tr>
            </thead>
            <tbody>
                {% for month, s in stats.items()|sort %}
                <tr>
                    <td>{{ month[:4] }}-{{ month[4:6] }}</td>
                    <td>{{ s.dates }} 天</td>
                    <td>{{ s.count }} 支</td>
                    <td>{{ "%.1f"|format(s.count / s.dates) if s.dates > 0 else '-' }} 支</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
```

- [ ] **Step 6: 编写 app.py**

```python
"""Flask Web 复盘页面入口。用法: python app.py"""
from flask import Flask
from web.routes import web


def create_app():
    app = Flask(__name__)
    app.register_blueprint(web)
    return app


if __name__ == "__main__":
    app = create_app()
    print("📊 选股复盘页面启动: http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
```

- [ ] **Step 7: 提交**

```bash
git add web/ app.py
git commit -m "feat: add Flask web review pages"
```

---

### Task 8: Git 同步脚本 — sync.sh

**Files:**
- Create: `sync.sh`
- Create: `sync.bat` (Windows 版)

- [ ] **Step 1: 创建 sync.sh (Git Bash)**

```bash
#!/bin/bash
# 手动同步选股数据
set -e
cd "$(dirname "$0")"

echo "=== Git 同步选股数据 ==="

echo "[1/3] 拉取远端..."
git pull --no-rebase

echo "[2/3] 添加本地结果..."
git add data/results/

if git diff --cached --quiet; then
    echo "  无新结果需要提交"
else
    git commit -m "results: sync $(date +%Y-%m-%d)"
fi

echo "[3/3] 推送到远端..."
git push

echo "=== 同步完成 ==="
```

- [ ] **Step 2: 创建 sync.bat (Windows)**

```bat
@echo off
cd /d "%~dp0"
echo === Git 同步选股数据 ===
echo [1/3] 拉取远端...
git pull --no-rebase
echo [2/3] 添加本地结果...
git add data\results\
git diff --cached --quiet
if %errorlevel% neq 1 (
    echo   无新结果需要提交
) else (
    git commit -m "results: sync %date%"
)
echo [3/3] 推送到远端...
git push
echo === 同步完成 ===
pause
```

- [ ] **Step 3: 提交**

```bash
git add sync.sh sync.bat
git commit -m "feat: add git sync scripts"
```

---

### Task 9: Windows 定时任务 & 使用文档

**Files:**
- Create: `README.md`

- [ ] **Step 1: 编写 README.md（使用说明）**

````markdown
# 自动化选股系统

## 环境准备

```bash
pip install -r requirements.txt
```

## 配置微信推送

1. 打开 https://www.pushplus.plus/ 注册
2. 复制你的 Token
3. 设置环境变量：

```powershell
# Windows PowerShell
[System.Environment]::SetEnvironmentVariable('PUSHPLUS_TOKEN', '你的token', 'User')
```

或每次运行前：
```bash
export PUSHPLUS_TOKEN=你的token
```

## 每日使用

```bash
# 收盘后运行（默认用今天日期）
python run.py

# 指定日期（复盘历史）
python run.py 20260601
```

## 查看复盘

```bash
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

## 两台电脑同步

### 首次配置

```bash
# 在 GitHub/Gitee 创建一个私有仓库，例如 my-stock-screener
git remote add origin <你的仓库地址>
git push -u origin main
```

### 另一台电脑

```bash
git clone <你的仓库地址>
pip install -r requirements.txt
# 同样设置 PUSHPLUS_TOKEN
```

### 日常同步

`run.py` 会自动 pull + push。如需手动同步：
- Windows: 双击 `sync.bat`
- Git Bash: `bash sync.sh`

## Windows 定时运行

1. 打开"任务计划程序"
2. 创建任务 → 触发器：每天 15:30
3. 操作：启动程序 `python`，参数 `F:\AI\STOCK\run.py`
````

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: add README with usage instructions"
```

---

### Task 10: 端到端验证

- [ ] **Step 1: 安装依赖**

```bash
cd /f/AI/STOCK
pip install -r requirements.txt
```

- [ ] **Step 2: 测试数据获取**

```bash
python -c "
from engine.fetcher import get_all_stock_codes
df = get_all_stock_codes()
print(f'股票数量: {len(df)}')
print(df.head())
"
```

- [ ] **Step 3: 测试单支股票K线拉取 + 涨停量修正**

```bash
python -c "
from engine.fetcher import fetch_daily_kline, correct_limit_up_volume
df = fetch_daily_kline('300750')
print(f'K线条数: {len(df)}')
print(df.tail())
"
```

- [ ] **Step 4: 测试完整筛选流程**

```bash
python -c "
from engine.screener import run_screening
results = run_screening()
print(f'筛选结果: {len(results)} 支')
for r in results[:5]:
    print(f\"  {r['code']} {r['name']} 1d:{r['ret_1d']}% 5d:{r['ret_5d']}%\")
"
```

- [ ] **Step 5: 测试 Flask Web 启动**

```bash
# 启动后浏览器打开 http://127.0.0.1:5000
python app.py
# Ctrl+C 退出
```

- [ ] **Step 6: 提交**

```bash
git add .
git commit -m "test: end-to-end verification complete"
```

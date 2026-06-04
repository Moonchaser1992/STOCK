"""市场情绪指标：涨跌比 + 涨停家数 + 成交额，综合打分 0-100"""
from __future__ import annotations
import os
import pandas as pd
import numpy as np
from datetime import datetime
import akshare as ak

from config import DATA_DIR

SENTIMENT_HISTORY = os.path.join(DATA_DIR, "results", "sentiment_history.csv")


def _get_limit_up_ratio(code: str) -> float:
    """返回涨停幅度"""
    code_str = str(code).zfill(6)
    if code_str.startswith(("300", "301", "688")):
        return 19.9
    elif code_str.startswith("8"):
        return 29.9
    else:
        return 9.9


def _load_history() -> pd.DataFrame:
    """加载历史情绪记录"""
    if os.path.exists(SENTIMENT_HISTORY):
        return pd.read_csv(SENTIMENT_HISTORY, encoding="utf-8-sig")
    return pd.DataFrame(columns=["date", "ad_ratio", "limit_up_count", "turnover_yi", "score"])


def _save_history(df: pd.DataFrame):
    """保存情绪记录"""
    os.makedirs(os.path.dirname(SENTIMENT_HISTORY), exist_ok=True)
    df.to_csv(SENTIMENT_HISTORY, index=False, encoding="utf-8-sig")


def compute_sentiment() -> dict:
    """
    计算当日市场情绪。
    返回: {
        "ad_ratio": 涨跌比,
        "limit_up_count": 涨停家数,
        "turnover_yi": 全市场成交额(亿),
        "score": 综合得分 0-100,
        "level": "乐观" / "中性" / "悲观",
        "suggestion": 操作建议文本
    }
    """
    print("\n[情绪判断] 获取市场数据...")

    # 获取全A股行情
    df = ak.stock_zh_a_spot()
    if df.empty:
        print("  [WARN] 无法获取行情数据，跳过情绪判断")
        return {"score": 50, "level": "中性", "suggestion": "数据缺失，自行判断", "ad_ratio": 0, "limit_up_count": 0, "turnover_yi": 0}

    # --- 指标1: 涨跌比 ---
    up = (df["涨跌幅"] > 0).sum()
    down = (df["涨跌幅"] < 0).sum()
    ad_ratio = up / down if down > 0 else 99.0
    # 归一化: 1.0->50分, 2.0->75分, 3.0->100分
    ad_score = min(100, max(0, 25 * ad_ratio + 25))

    # --- 指标2: 涨停家数 ---
    limit_up_count = 0
    for _, row in df.iterrows():
        code = str(row["代码"])
        chg = row["涨跌幅"]
        if pd.notna(chg) and chg >= _get_limit_up_ratio(code):
            limit_up_count += 1

    # 归一化: 50家->50分, 100家->75分, 200家->100分
    lu_score = min(100, max(0, 25 * np.log2(max(limit_up_count, 1))))

    # --- 指标3: 成交额 ---
    total_turnover = df["成交额"].sum()  # 单位: 元
    turnover_yi = total_turnover / 1e8  # 转为亿元

    # 读取历史，对比近20日均值
    history = _load_history()
    if len(history) >= 5:
        avg_turnover = history["turnover_yi"].tail(20).mean()
        if avg_turnover > 0:
            ratio = turnover_yi / avg_turnover
            # 成交额对比: 0.8倍->40分, 1.0倍->50分, 1.5倍->80分, 2倍->100分
            to_score = min(100, max(0, 50 * ratio))
        else:
            to_score = 50
    else:
        to_score = 50  # 历史不足，默认中性

    # --- 综合得分 ---
    # 涨跌比40% + 涨停数30% + 成交额30%
    score = round(ad_score * 0.4 + lu_score * 0.3 + to_score * 0.3)

    if score >= 60:
        level = "乐观"
        suggestion = "情绪积极，正常操作"
    elif score >= 40:
        level = "中性"
        suggestion = "情绪一般，谨慎参与"
    else:
        level = "悲观"
        suggestion = "情绪低迷，建议观望"

    print(f"  涨跌比: {ad_ratio:.2f} ({ad_score}分) | 涨停: {limit_up_count}家 ({lu_score}分) | 成交额: {turnover_yi:.0f}亿 ({to_score}分)")
    print(f"  综合: {score}分 [{level}] — {suggestion}")

    # 保存今日记录
    new_row = pd.DataFrame([{
        "date": datetime.now().strftime("%Y%m%d"),
        "ad_ratio": round(ad_ratio, 2),
        "limit_up_count": limit_up_count,
        "turnover_yi": round(turnover_yi, 0),
        "score": score,
    }])
    history = pd.concat([history, new_row], ignore_index=True)
    # 去重
    history = history.drop_duplicates(subset=["date"], keep="last")
    _save_history(history)

    return {
        "ad_ratio": round(ad_ratio, 2),
        "limit_up_count": limit_up_count,
        "turnover_yi": round(turnover_yi, 0),
        "score": score,
        "level": level,
        "suggestion": suggestion,
    }

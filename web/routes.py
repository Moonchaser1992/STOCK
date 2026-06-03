"""Flask 路由：复盘页面"""
import os
from datetime import datetime

from flask import Blueprint, render_template, request

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

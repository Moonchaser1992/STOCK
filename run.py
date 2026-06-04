#!/usr/bin/env python
"""每日一键选股入口。用法: python run.py [YYYYMMDD]"""
import sys
import subprocess
from datetime import datetime

# Windows 控制台 UTF-8 支持
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from config import GIT_AUTO_SYNC
from engine.sentiment import compute_sentiment
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

    # 市场情绪判断
    sentiment = compute_sentiment()

    # 执行筛选
    results = run_screening(trade_date, sentiment=sentiment)

    # 推送微信
    send_stock_results(results, trade_date)

    # 同步结果到远端
    if GIT_AUTO_SYNC:
        git_push()

    print(f"\n✅ 选股完成！共 {len(results)} 支进入观察池")
    print(f"📊 市场情绪: {sentiment['level']} ({sentiment['score']}分)")
    if sentiment['score'] < 40:
        print(f"⚠️  {sentiment['suggestion']}")
    print(f"💻 复盘页面: python app.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中止")
    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
        print("\n程序异常退出，请检查错误信息。")
        if sys.platform == "win32":
            input("按 Enter 关闭...")

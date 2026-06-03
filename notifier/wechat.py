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

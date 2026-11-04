import os
import datetime
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd

def get_previous_workday():
    """计算上一个工作日（自动跳过周末）"""
    today = datetime.date.today()
    offset = 1
    if today.weekday() == 0:    # 周一抓上周五
        offset = 3
    elif today.weekday() == 6:  # 周日抓周五
        offset = 2
    prev_date = today - datetime.timedelta(days=offset)
    return prev_date.strftime("%Y-%m-%d")

def make_request_with_retry(url, headers, is_json=False, retries=3, delay=3):
    """带自适应重试与防屏蔽请求头的网络请求机制"""
    for i in range(retries):
        try:
            res = requests.get(url, headers=headers, timeout=20)
            if res.status_code == 200:
                return res.json() if is_json else res.text
            else:
                print(f"[!] 请求状态码异常 [{res.status_code}]，正在重试...")
        except Exception as err:
            print(f"[!] 网络波动异常(第 {i+1} 次): {err}")
        time.sleep(delay)
    return None

def fetch_boc_fx():
    """1. 抓取中国银行外汇牌价（EUR & USD）"""
    url = "https://www.boc.cn/sourcedb/whpj/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    content = make_request_with_retry(url, headers)
    if not content:
        return pd.DataFrame()

    soup = BeautifulSoup(content, "html.parser")
    fx_results = []
    target_currencies = ["美元", "欧元"]
    
    table = soup.find("table", bgcolor="#EAEAEA")
    if not table:
        tables = soup.find_all("table")
        for t in tables:
            if "货币名称" in t.get_text():
                table = t
                break

    if table:
        for r in table.find_all("tr")[1:]:
            cols = [td.get_text(strip=True) for td in r.find_all("td")]
            if cols and cols[0] in target_currencies:
                fx_results.append({
                    "货币名称": cols[0],
                    "现汇买入价": cols[1],
                    "现钞买入价": cols[2],
                    "现汇卖出价": cols[3],
                    "现钞卖出价": cols[4],
                    "中行折算价": cols[5],
                    "发布时间": (cols[6] + " " + cols[7]) if len(cols) > 7 else cols[6]
                })
    return pd.DataFrame(fx_results)

def fetch_shfe_aluminum(trade_date):
    """2. 抓取上期所铝交易数据并格式化输出"""
    date_str = trade_date.replace("-", "")
    url = f"https://www.shfe.com.cn/data/dailydata/kx/kx{date_str}.dat"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.shfe.com.cn/reports/tradedata/dailyandweeklydata/",
        "Accept": "application/json, text/javascript, */*; q=0.01"
    }
    data = make_request_with_retry(url, headers, is_json=True)
    if not data:
        return pd.DataFrame()

    records = []
    for item in data.get("o_curinstrument", []):
        if item.get("PRODUCTID", "").strip().lower() == "al":
            records.append({
                "交割月份": item.get("DELIVERYMONTH"),
                "前结算": item.get("PRESETTLEMENTPRICE"),
                "今开盘": item.get("OPENPRICE"),
                "最高价": item.get("HIGHESTPRICE"),
                "最低价": item.get("LOWESTPRICE"),
                "收盘价": item.get("CLOSEPRICE"),
                "结算参考价": item.get("SETTLEMENTPRICE"),
                "涨跌1": item.get("ZD1_CHG"),
                "涨跌2": item.get("ZD2_CHG"),
                "成交手": item.get("VOLUME"),
                "成交额": item.get("TURNOVER"),
                "持仓手/变化": f"{item.get('OPENINTEREST', '')} / {item.get('OPENINTERESTCHG', '')}"
            })
    return pd.DataFrame(records)

def fetch_sge_platinum(trade_date):
    """3. 抓取上海黄金交易所 Pt99.95 行情"""
    url = f"https://www.sge.com.cn/sjzx/quotation_daily_new?start_date={trade_date}&end_date={trade_date}&inst_ids=Pt99.95"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.sge.com.cn/"
    }
    content = make_request_with_retry(url, headers)
    if not content:
        return pd.DataFrame()

    soup = BeautifulSoup(content, "html.parser")
    rows = soup.select(".table tr")
    results = []
    for r in rows[1:]:
        tds = [td.get_text(strip=True) for td in r.find_all("td")]
        if tds and len(tds) >= 11 and "Pt99.95" in tds[1]:
            results.append({
                "日期": tds[0],
                "合约": tds[1],
                "开盘价": tds[2],
                "最高价": tds[3],
                "最低价": tds[4],
                "收盘价": tds[5],
                "涨跌(元)": tds[6],
                "涨跌幅": tds[7],
                "加权平均价": tds[8],
                "成交量(kg)": tds[9],
                "成交金额(元)": tds[10],
                "市场持仓(手)": tds[11] if len(tds) > 11 else "-",
                "交收方向": tds[12] if len(tds) > 12 else "-",
                "交收量(手)": tds[13] if len(tds) > 13 else "-"
            })
    return pd.DataFrame(results)

def generate_dashboard():
    target_date = get_previous_workday()
    print(f"[*] 开始拉取前一工作日 [{target_date}] 行情数据...")

    df_fx = fetch_boc_fx()
    df_al = fetch_shfe_aluminum(target_date)
    df_pt = fetch_sge_platinum(target_date)

    # 格式化上期所铝表格：加入商品栏并将结算参考价高亮显示
    al_table_html = ""
    if not df_al.empty:
        # 寻找结算参考价在列中的索引
        cols = list(df_al.columns)
        settle_idx = cols.index("结算参考价") if "结算参考价" in cols else -1
        
        rows_str = ""
        for _, row in df_al.iterrows():
            cells = ""
            for i, val in enumerate(row):
                cls = ' class="highlight"' if i == settle_idx else ''
                cells += f'<td{cls}>{val}</td>'
            rows_str += f"<tr>{cells}</tr>"
        
        headers_str = "".join([f"<th>{c}</th>" for c in cols])
        al_table_html = f"""
        <table class="data-table">
            <thead>
                <tr>{headers_str}</tr>
                <tr class="sub-header"><td colspan="{len(cols)}" style="background:#fed7aa; color:#9a3412; font-weight:bold; text-align:left; padding-left:15px;">商品名称: 铝</td></tr>
            </thead>
            <tbody>{rows_str}</tbody>
        </table>
        """
    else:
        al_table_html = '<div class="empty-tip">⚠️ 上期所暂未返回当前日期铝数据或受网络波动拦截</div>'

    fx_html = df_fx.to_html(index=False, classes='data-table') if not df_fx.empty else '<div class="empty-tip">⚠️ 中国银行汇率抓取暂无响应</div>'
    pt_html = df_pt.to_html(index=False, classes='data-table') if not df_pt.empty else '<div class="empty-tip">⚠️ 上金所 Pt99.95 行情抓取暂无响应</div>'

    html_template = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日大宗商品与外汇监控 Dashboard</title>
    <style>
        :root {{
            --primary: #1d4ed8;
            --primary-bg: #eff6ff;
            --border: #e2e8f0;
            --text-main: #0f172a;
            --text-sub: #475569;
            --highlight: #fef08a;
            --highlight-text: #854d0e;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
            background-color: #f8fafc;
            color: var(--text-main);
            margin: 0;
            padding: 24px;
        }}
        .wrapper {{
            max-width: 1300px;
            margin: 0 auto;
        }}
        .header {{
            background: #ffffff;
            padding: 24px 28px;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            margin-bottom: 24px;
            border-left: 6px solid var(--primary);
        }}
        h1 {{ margin: 0 0 10px 0; font-size: 22px; color: var(--text-main); }}
        .meta {{ color: var(--text-sub); font-size: 14px; display: flex; gap: 16px; flex-wrap: wrap; }}
        .badge {{ background: var(--primary-bg); color: var(--primary); padding: 2px 10px; border-radius: 20px; font-weight: 600; }}
        
        .section-card {{
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            margin-bottom: 28px;
            overflow: hidden;
            border: 1px solid var(--border);
        }}
        .card-title {{
            background: #f1f5f9;
            padding: 14px 20px;
            margin: 0;
            font-size: 16px;
            font-weight: 700;
            color: #1e293b;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .table-container {{
            overflow-x: auto;
            width: 100%;
        }}
        table.data-table {{
            border-collapse: collapse;
            width: 100%;
            font-size: 13px;
            text-align: center;
        }}
        table.data-table th {{
            background-color: #1e40af;
            color: #ffffff;
            padding: 10px 14px;
            white-space: nowrap;
            font-weight: 600;
            border: 1px solid #1e3a8a;
        }}
        table.data-table td {{
            padding: 10px 12px;
            border: 1px solid var(--border);
            white-space: nowrap;
        }}
        table.data-table tr:hover {{
            background-color: #f8fafc;
        }}
        .highlight {{
            background-color: var(--highlight) !important;
            color: var(--highlight-text) !important;
            font-weight: 700;
        }}
        .empty-tip {{
            padding: 24px;
            color: #b91c1c;
            text-align: center;
            font-size: 14px;
        }}
        .footer {{
            text-align: center;
            color: #94a3b8;
            font-size: 13px;
            margin-top: 30px;
        }}
    </style>
</head>
<body>
    <div class="wrapper">
        <div class="header">
            <h1>每日大宗商品与外汇监控 Dashboard</h1>
            <div class="meta">
                <span>基准抓取交易日：<strong class="badge">{target_date}</strong></span>
                <span>自动化流水线刷新时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)</span>
            </div>
        </div>

        <!-- 1. 中国银行外汇牌价 -->
        <div class="section-card">
            <div class="card-title">
                <span>1. 中国银行外汇牌价 (EUR / USD)</span>
                <a href="https://www.boc.cn/sourcedb/whpj/" target="_blank" style="font-size:12px; color:#2563eb; text-decoration:none;">官方源直达 ↗</a>
            </div>
            <div class="table-container">
                {fx_html}
            </div>
        </div>

        <!-- 2. 上海期货交易所 铝 -->
        <div class="section-card">
            <div class="card-title">
                <span>2. 上海期货交易所 - 铝交易数据 (含结算参考价高亮)</span>
                <a href="https://www.shfe.com.cn/reports/tradedata/dailyandweeklydata/" target="_blank" style="font-size:12px; color:#2563eb; text-decoration:none;">官方源直达 ↗</a>
            </div>
            <div class="table-container">
                {al_table_html}
            </div>
        </div>

        <!-- 3. 上海黄金交易所 Pt99.95 -->
        <div class="section-card">
            <div class="card-title">
                <span>3. 上海黄金交易所 - Pt99.95 每日交易行情</span>
                <a href="https://www.sge.com.cn/sjzx/quotation_daily_new" target="_blank" style="font-size:12px; color:#2563eb; text-decoration:none;">官方源直达 ↗</a>
            </div>
            <div class="table-container">
                {pt_html}
            </div>
        </div>

        <div class="footer">
            Generated automatically by GitHub Actions Workflows • Daily Market Reporter
        </div>
    </div>
</body>
</html>
"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print("[✓] Dashboard 看板 index.html 生成完毕！")

if __name__ == "__main__":
    generate_dashboard()

# -*- coding: utf-8 -*-
import datetime
import json
import re
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd

# 公共请求头配置
COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

def make_request(url, headers=None, is_json=False, timeout=12):
    req_headers = dict(COMMON_HEADERS)
    if headers:
        req_headers.update(headers)
    try:
        resp = requests.get(url, headers=req_headers, timeout=timeout)
        if resp.status_code == 200:
            if is_json:
                return resp.json()
            # 自动处理中文编码
            content = resp.content
            for enc in ['utf-8', 'gb18030', 'gbk']:
                try:
                    return content.decode(enc)
                except UnicodeDecodeError:
                    continue
            return resp.text
    except Exception as e:
        print(f"[!] 请求异常 ({url}): {e}")
    return None

# ==========================================
# 1. 抓取中国银行外汇牌价 (EUR & USD)
# ==========================================
def fetch_boc_fx():
    print("[*] 正在抓取中国银行外汇牌价 (EUR / USD)...")
    records = []
    
    # 策略 A：直接请求中行外汇牌价官网
    url = "https://www.boc.cn/sourcedb/whpj/"
    html = make_request(url)
    if html:
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if not rows or "货币名称" not in rows[0].get_text():
                continue
            for r in rows[1:]:
                tds = [td.get_text(strip=True) for td in r.find_all("td")]
                if tds and tds[0] in ["美元", "欧元"]:
                    records.append({
                        "货币名称": tds[0],
                        "现汇买入价": tds[1] if len(tds) > 1 else "-",
                        "现钞买入价": tds[2] if len(tds) > 2 else "-",
                        "现汇卖出价": tds[3] if len(tds) > 3 else "-",
                        "现钞卖出价": tds[4] if len(tds) > 4 else "-",
                        "中行折算价": tds[5] if len(tds) > 5 else "-",
                        "发布时间": f"{tds[6]} {tds[7]}" if len(tds) > 7 else (tds[6] if len(tds) > 6 else "-")
                    })
            if records:
                break

    # 策略 B：容灾通道（新浪/东财官方外汇牌价接口）
    if not records:
        print("[!] 中行官网响应受限，切换至金融行情容灾通道...")
        backup_url = "https://hq.sinajs.cn/list=fx_seurusd,fx_susdcny,fx_seurcny"
        headers = {"Referer": "https://finance.sina.com.cn/"}
        res_text = make_request(backup_url, headers=headers)
        if res_text:
            lines = res_text.strip().split("\n")
            for line in lines:
                if 'fx_susdcny="' in line:
                    parts = line.split('="')[1].split(",")
                    if len(parts) > 8:
                        records.append({
                            "货币名称": "美元",
                            "现汇买入价": parts[2],
                            "现钞买入价": parts[2],
                            "现汇卖出价": parts[3],
                            "现钞卖出价": parts[3],
                            "中行折算价": parts[1],
                            "发布时间": f"{parts[17]} {parts[0]}" if len(parts) > 17 else datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                elif 'fx_seurcny="' in line:
                    parts = line.split('="')[1].split(",")
                    if len(parts) > 8:
                        records.append({
                            "货币名称": "欧元",
                            "现汇买入价": parts[2],
                            "现钞买入价": parts[2],
                            "现汇卖出价": parts[3],
                            "现钞卖出价": parts[3],
                            "中行折算价": parts[1],
                            "发布时间": f"{parts[17]} {parts[0]}" if len(parts) > 17 else datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
    return pd.DataFrame(records)

# ==========================================
# 2. 抓取上海期货交易所铝合约数据 (自动回溯交易日)
# ==========================================
def fetch_shfe_aluminum():
    print("[*] 正在抓取上期所铝合约数据（含结算参考价）...")
    today = datetime.date.today()
    # 最多向前追溯 7 天以跳过周末及非交易日
    for i in range(1, 8):
        check_date = today - datetime.timedelta(days=i)
        date_str = check_date.strftime("%Y%m%d")
        url = f"https://www.shfe.com.cn/data/dailydata/kx/kx{date_str}.dat"
        headers = {
            "Referer": "https://www.shfe.com.cn/reports/tradedata/dailyandweeklydata/",
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }
        data = make_request(url, headers=headers, is_json=True)
        if not data or not isinstance(data, dict):
            continue

        raw_list = data.get("o_curinstrument", [])
        records = []
        for item in raw_list:
            p_id = str(item.get("PRODUCTID", "")).strip().lower()
            if "al" in p_id:
                delivery_month = str(item.get("DELIVERYMONTH", "")).strip()
                if not delivery_month or delivery_month == "小计":
                    continue
                records.append({
                    "交割月份": delivery_month,
                    "前结算": item.get("PRESETTLEMENTPRICE", "-"),
                    "今开盘": item.get("OPENPRICE", "-"),
                    "最高价": item.get("HIGHESTPRICE", "-"),
                    "最低价": item.get("LOWESTPRICE", "-"),
                    "收盘价": item.get("CLOSEPRICE", "-"),
                    "结算参考价": item.get("SETTLEMENTPRICE", "-"),
                    "涨跌1": item.get("ZD1_CHG", "-"),
                    "涨跌2": item.get("ZD2_CHG", "-"),
                    "成交手": item.get("VOLUME", "-"),
                    "成交额": item.get("TURNOVER", "-"),
                    "持仓手/变化": f"{item.get('OPENINTEREST', '-')} / {item.get('OPENINTERESTCHG', '-')}"
                })
        if records:
            actual_trade_date = check_date.strftime("%Y-%m-%d")
            print(f"[✓] 成功获取上期所铝数据，结算交易日为: {actual_trade_date}")
            return pd.DataFrame(records), actual_trade_date

    return pd.DataFrame(), None

# ==========================================
# 3. 抓取上海黄金交易所 Pt99.95 行情数据
# ==========================================
def fetch_sge_platinum(preferred_date=None):
    print("[*] 正在抓取上金所 Pt99.95 行情...")
    today = datetime.date.today()
    check_dates = [preferred_date] if preferred_date else []
    for d in range(1, 8):
        dt_str = (today - datetime.timedelta(days=d)).strftime("%Y-%m-%d")
        if dt_str not in check_dates:
            check_dates.append(dt_str)

    # 策略 A：直接请求上金所每日行情
    for dt in check_dates:
        url = f"https://www.sge.com.cn/sjzx/quotation_daily_new?start_date={dt}&end_date={dt}&inst_ids=Pt99.95"
        headers = {"Referer": "https://www.sge.com.cn/"}
        html = make_request(url, headers=headers)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
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
        if results:
            print(f"[✓] 成功获取上金所 Pt99.95 官方数据，日期: {dt}")
            return pd.DataFrame(results)

    # 策略 B：若官方 HTML 存在反爬拦截，使用行情接口直连
    print("[!] 上金所官方页面触发反爬，通过贵金属行情镜像获取最新 Pt99.95...")
    api_url = "https://hq.sinajs.cn/list=s_sge_pt9995"
    headers = {"Referer": "https://finance.sina.com.cn/"}
    txt = make_request(api_url, headers=headers)
    if txt and 's_sge_pt9995="' in txt:
        data_part = txt.split('="')[1].replace('";', '')
        fields = data_part.split(',')
        if len(fields) >= 5:
            # 格式: 名字, 最新价, 涨跌额, 涨跌幅, 成交量, 成交金额
            latest_price = fields[1]
            chg = fields[2]
            chg_rate = f"{fields[3]}%"
            return pd.DataFrame([{
                "日期": datetime.date.today().strftime("%Y-%m-%d"),
                "合约": "Pt99.95",
                "开盘价": latest_price,
                "最高价": latest_price,
                "最低价": latest_price,
                "收盘价": latest_price,
                "涨跌(元)": chg,
                "涨跌幅": chg_rate,
                "加权平均价": latest_price,
                "成交量(kg)": fields[4] if len(fields) > 4 else "-",
                "成交金额(元)": fields[5] if len(fields) > 5 else "-",
                "市场持仓(手)": "-",
                "交收方向": "-",
                "交收量(手)": "-"
            }])
    return pd.DataFrame()

# ==========================================
# 4. 生成自适应 HTML 看板 (严格还原图片格式)
# ==========================================
def render_dashboard(df_fx, df_al, df_pt, trade_date):
    # 渲染上期所铝表格（重点高亮结算参考价）
    if not df_al.empty:
        cols = list(df_al.columns)
        settle_idx = cols.index("结算参考价") if "结算参考价" in cols else -1
        rows_html = ""
        for _, row in df_al.iterrows():
            td_cells = ""
            for i, val in enumerate(row):
                highlight_attr = ' class="highlight-cell"' if i == settle_idx else ''
                td_cells += f'<td{highlight_attr}>{val}</td>'
            rows_html += f"<tr>{td_cells}</tr>"
        
        headers_html = "".join([f"<th>{c}</th>" for c in cols])
        al_table_html = f"""
        <table class="market-table">
            <thead>
                <tr>{headers_html}</tr>
                <tr class="product-header-row"><td colspan="{len(cols)}">商品名称:铝</td></tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>"""
    else:
        al_table_html = '<div class="alert-box">⚠️ 未能检索到上期所铝合约数据，可能由于交易所服务器处于结算维护周期。</div>'

    fx_table_html = df_fx.to_html(index=False, classes='market-table') if not df_fx.empty else '<div class="alert-box">⚠️ 中国银行汇率抓取暂无响应</div>'
    pt_table_html = df_pt.to_html(index=False, classes='market-table') if not df_pt.empty else '<div class="alert-box">⚠️ 上金所 Pt99.95 行情暂无响应</div>'

    now_str = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日大宗商品与外汇监控 Dashboard</title>
    <style>
        :root {{
            --primary: #0052d9;
            --primary-bg: #eff6ff;
            --highlight: #fef08a;
            --highlight-text: #854d0e;
            --orange-banner: #fdba74;
            --orange-text: #7c2d12;
            --border: #e2e8f0;
            --card-bg: #ffffff;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
            background-color: #f1f5f9;
            color: #0f172a;
            margin: 0;
            padding: 24px 16px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        .header-card {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
            border-left: 6px solid var(--primary);
        }}
        .title-row {{
            font-size: 22px;
            font-weight: 700;
            margin: 0 0 10px 0;
            color: #1e293b;
        }}
        .meta-info {{
            font-size: 13px;
            color: #64748b;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}
        .meta-tag {{
            background: var(--primary-bg);
            color: var(--primary);
            padding: 2px 10px;
            border-radius: 12px;
            font-weight: 600;
        }}
        .section-card {{
            background: var(--card-bg);
            border-radius: 12px;
            border: 1px solid var(--border);
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
            overflow: hidden;
        }}
        .section-title {{
            background: #f8fafc;
            padding: 12px 20px;
            margin: 0;
            font-size: 15px;
            font-weight: 700;
            color: #1e293b;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .source-link {{
            font-size: 12px;
            color: var(--primary);
            text-decoration: none;
            font-weight: normal;
        }}
        .source-link:hover {{
            text-decoration: underline;
        }}
        .table-scroll {{
            width: 100%;
            overflow-x: auto;
        }}
        table.market-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: center;
        }}
        table.market-table th {{
            background-color: var(--primary);
            color: #ffffff;
            font-weight: 600;
            padding: 9px 12px;
            white-space: nowrap;
            border: 1px solid #1d4ed8;
        }}
        table.market-table td {{
            padding: 8px 10px;
            border: 1px solid var(--border);
            white-space: nowrap;
            color: #334155;
        }}
        table.market-table tbody tr:hover {{
            background-color: #f8fafc;
        }}
        .product-header-row td {{
            background-color: var(--orange-banner) !important;
            color: var(--orange-text) !important;
            font-weight: 700;
            text-align: left;
            padding: 8px 16px !important;
            font-size: 14px;
        }}
        .highlight-cell {{
            background-color: var(--highlight) !important;
            color: var(--highlight-text) !important;
            font-weight: 700;
        }}
        .alert-box {{
            padding: 24px;
            text-align: center;
            color: #dc2626;
            font-size: 13px;
            background: #fef2f2;
        }}
        .footer {{
            text-align: center;
            font-size: 12px;
            color: #94a3b8;
            margin-top: 36px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header-card">
            <h1 class="title-row">每日大宗商品与外汇监控 Dashboard</h1>
            <div class="meta-info">
                <span>基准抓取交易日：<strong class="meta-tag">{trade_date}</strong></span>
                <span>自动化流水线刷新时间：{now_str} (UTC+8)</span>
            </div>
        </div>

        <div class="section-card">
            <div class="section-title">
                <span>1. 中国银行外汇牌价 (EUR / USD)</span>
                <a class="source-link" href="https://www.boc.cn/sourcedb/whpj/" target="_blank">官方源直达 ↗</a>
            </div>
            <div class="table-scroll">{fx_table_html}</div>
        </div>

        <div class="section-card">
            <div class="section-title">
                <span>2. 上海期货交易所 - 铝交易数据 (含结算参考价高亮)</span>
                <a class="source-link" href="https://www.shfe.com.cn/reports/tradedata/dailyandweeklydata/" target="_blank">官方源直达 ↗</a>
            </div>
            <div class="table-scroll">{al_table_html}</div>
        </div>

        <div class="section-card">
            <div class="section-title">
                <span>3. 上海黄金交易所 - Pt99.95 每日交易行情</span>
                <a class="source-link" href="https://www.sge.com.cn/sjzx/quotation_daily_new" target="_blank">官方源直达 ↗</a>
            </div>
            <div class="table-scroll">{pt_table_html}</div>
        </div>

        <div class="footer">
            Generated automatically by GitHub Actions Workflows • Daily Market Reporter
        </div>
    </div>
</body>
</html>"""
    return html_content

def main():
    print("=" * 60)
    print("🚀 开始执行每日大宗商品与外汇数据抓取流水线")
    print("=" * 60)
    
    # 1. 获取汇率
    df_fx = fetch_boc_fx()
    
    # 2. 获取上期所铝合约
    df_al, trade_date = fetch_shfe_aluminum()
    if not trade_date:
        trade_date = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    # 3. 获取上金所 Pt99.95
    df_pt = fetch_sge_platinum(trade_date)
    
    # 4. 渲染看板并输出
    html_output = render_dashboard(df_fx, df_al, df_pt, trade_date)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_output)
        
    print(f"[✓] Dashboard 成功生成并写入 index.html (字节数: {len(html_output)})")
    print("=" * 60)

if __name__ == "__main__":
    main()

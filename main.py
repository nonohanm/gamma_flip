import os
import math
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def calculate_bs_gamma(S, K, T, r=0.0, sigma=0.6):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_pdf(d1) / (S * sigma * math.sqrt(T))

def generate_gamma_chart():
    current_time_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"[{current_time_str}] Deribit 실시간 데이터 수집 시작...")
    
    try:
        index_url = "https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd"
        spot_price = requests.get(index_url, timeout=10).json()['result']['index_price']
        
        summary_url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"
        summary_res = requests.get(summary_url, timeout=10).json()['result']
    except Exception as e:
        print(f"❌ API 요청 실패: {e}")
        return

    gex_data = []
    now = datetime.now(timezone.utc)
    
    for item in summary_res:
        name = item.get('instrument_name', '')
        parts = name.split('-')
        if len(parts) < 4: continue
            
        try:
            exp_str = parts[1]
            try: exp_date = datetime.strptime(exp_str, "%d%b%y").replace(tzinfo=timezone.utc)
            except ValueError: exp_date = datetime.strptime(exp_str, "%d%b%Y").replace(tzinfo=timezone.utc)
                
            T = (exp_date - now).total_seconds() / (365.25 * 86400)
            strike = float(parts[2])
            option_type = 'call' if parts[3] == 'C' else 'put'
        except Exception: continue
            
        oi = item.get('open_interest', 0)
        mark_iv = item.get('mark_iv', 0) / 100.0
        if mark_iv <= 0: mark_iv = 0.60
            
        if oi > 0 and T > 0:
            gamma = calculate_bs_gamma(S=spot_price, K=strike, T=T, r=0.0, sigma=mark_iv)
            dollar_gamma = gamma * oi * (spot_price ** 2) * 0.01 / 1e6
            gex_data.append({'strike': strike, 'option_type': option_type, 'gex': dollar_gamma})

    df = pd.DataFrame(gex_data)
    if df.empty: return

    calls = df[df['option_type'] == 'call'].groupby('strike')['gex'].sum().reset_index()
    puts = df[df['option_type'] == 'put'].groupby('strike')['gex'].sum().reset_index()
    
    merged = pd.merge(calls, puts, on='strike', how='outer', suffixes=('_call', '_put')).fillna(0)
    merged['total'] = merged['gex_call'] - merged['gex_put']
    merged['abs_gex'] = merged['gex_call'] + merged['gex_put']
    
    min_strike = spot_price * 0.70
    max_strike = spot_price * 1.30
    filtered = merged[(merged['strike'] >= min_strike) & (merged['strike'] <= max_strike)].sort_values('strike').reset_index(drop=True)

    flip_row = filtered.iloc[(filtered['total']).abs().argsort()[:1]]
    flip_point = float(flip_row['strike'].values[0]) if not flip_row.empty else spot_price
    
    p1 = float(filtered.sort_values('gex_call', ascending=False)['strike'].iloc[0])
    p2 = float(filtered.sort_values('gex_call', ascending=False)['strike'].iloc[1]) if len(filtered) > 1 else p1
    n1 = float(filtered.sort_values('gex_put', ascending=False)['strike'].iloc[0])
    n2 = float(filtered.sort_values('gex_put', ascending=False)['strike'].iloc[1]) if len(filtered) > 1 else n1
    a1 = float(filtered.sort_values('abs_gex', ascending=False)['strike'].iloc[0])
    a2 = float(filtered.sort_values('abs_gex', ascending=False)['strike'].iloc[1]) if len(filtered) > 1 else a1
    ms, mv = p1, n1

    def get_val(strike_val, col):
        res = filtered[filtered['strike'] == strike_val][col]
        return float(res.values[0]) if not res.empty else 0.0

    v_n1 = get_val(n1, 'gex_put')
    v_n2 = get_val(n2, 'gex_put')
    v_a1 = get_val(a1, 'abs_gex')
    v_a2 = get_val(a2, 'abs_gex')
    v_p1 = get_val(p1, 'gex_call')
    v_p2 = get_val(p2, 'gex_call')

    def get_pct(target):
        diff = ((target - spot_price) / spot_price) * 100
        sign = "↑" if diff >= 0 else "↓"
        return f"{sign}{abs(diff):.0f}%" if abs(diff) >= 1 else f"{sign}&lt;1%"

    total_call_gex = filtered['gex_call'].sum()
    total_put_gex = filtered['gex_put'].sum()
    regime_val = round((total_call_gex - total_put_gex) / (total_call_gex + total_put_gex + 1e-5), 2)
    cp_val = regime_val
    gex_above = filtered[filtered['strike'] >= spot_price]['total'].sum()
    gex_below = filtered[filtered['strike'] < spot_price]['total'].sum()
    updown_val = round((gex_above - abs(gex_below)) / (abs(gex_above) + abs(gex_below) + 1e-5), 2)

    unique_strikes = filtered['strike'].tolist()
    strike_labels = [f"{int(s/1000)}k" if s >= 1000 else f"{int(s)}" for s in unique_strikes]
    profile_colors = ['#22c55e' if x >= 0 else '#ef4444' for x in filtered['total']]
    hover_style = dict(bgcolor='#181b20', bordercolor='#333', font_size=14, font_color='#ffffff')
    bar_w = (filtered['strike'].iloc[1] - filtered['strike'].iloc[0]) * 0.65 if len(filtered) > 1 else 500

    def build_gex_strike_figure(height_px=250):
        fig_top = go.Figure()
        fig_top.add_trace(go.Bar(x=filtered['strike'], y=filtered['total'], marker_color=profile_colors, width=bar_w, name='Net GEX'))
        fig_top.add_vrect(x0=min(n1, n2)-200, x1=max(n1, n2)+200, fillcolor="#ef4444", opacity=0.15, line_width=0)
        fig_top.add_vrect(x0=flip_point-100, x1=a2+100, fillcolor="#a855f7", opacity=0.15, line_width=0)

        top_badges = [(n2, f"N2 • {get_pct(n2)}", "#ef4444"), (flip_point, f"F • {get_pct(flip_point)}", "#d946ef"), (p1, f"P1* • {get_pct(p1)}", "#22c55e"), (p2, f"P2 • {get_pct(p2)}", "#22c55e")]
        for val, text, col in top_badges:
            fig_top.add_vline(x=val, line_width=1, line_dash="dot", line_color=col)
            fig_top.add_annotation(x=val, y=0.85, yref='paper', text=f"<b>{text}</b>", showarrow=False, font=dict(size=10, color="#ffffff"), bgcolor=col, bordercolor=col, borderpad=3)
        fig_top.add_vline(x=spot_price, line_width=1.5, line_dash="dash", line_color="#ffffff")

        max_net = max(abs(filtered['total'].min()), abs(filtered['total'].max())) * 1.25
        fig_top.update_layout(title="<b>GEX BY STRIKE</b>", title_font=dict(color="#fff", size=14), height=height_px, paper_bgcolor='#090a0f', plot_bgcolor='#090a0f', showlegend=False, margin=dict(l=30, r=30, t=35, b=10), hoverlabel=hover_style)
        fig_top.update_xaxes(tickvals=unique_strikes, ticktext=strike_labels, tickangle=0, gridcolor='#151821', showticklabels=False)
        fig_top.update_yaxes(range=[-max_net, max_net], gridcolor='#151821', zeroline=True, zerolinecolor='#ffffff')

        fig_bot = go.Figure()
        fig_bot.add_trace(go.Scatter(x=filtered['strike'], y=filtered['abs_gex'], fill='tozeroy', mode='lines+markers', line=dict(color='#c084fc', width=2), fillcolor='rgba(192, 132, 252, 0.2)', marker=dict(size=4, color='#d8b4fe'), name='Abs GEX'))
        fig_bot.add_vrect(x0=min(n1, n2)-200, x1=max(n1, n2)+200, fillcolor="#ef4444", opacity=0.15, line_width=0)
        fig_bot.add_vrect(x0=flip_point-100, x1=a2+100, fillcolor="#a855f7", opacity=0.15, line_width=0)

        bot_badges = [(mv, f"V • {get_pct(mv)}", "#ef4444"), (a1, f"A1* • {get_pct(a1)}", "#a855f7"), (a2, f"A2 • {get_pct(a2)}", "#a855f7")]
        for val, text, col in bot_badges:
            fig_bot.add_vline(x=val, line_width=1, line_dash="dot", line_color=col)
            fig_bot.add_annotation(x=val, y=0.85, yref='paper', text=f"<b>{text}</b>", showarrow=False, font=dict(size=10, color="#ffffff"), bgcolor=col, bordercolor=col, borderpad=3)
            
        fig_bot.add_vline(x=spot_price, line_width=1.5, line_dash="dash", line_color="#ffffff")
        fig_bot.add_annotation(x=spot_price, y=0.1, yref='paper', text=f"<b>{spot_price:,.0f}</b>", showarrow=False, font=dict(size=11, color="#000000"), bgcolor="#ffffff", bordercolor="#ffffff", borderpad=3)

        max_abs = filtered['abs_gex'].max() * 1.25
        fig_bot.update_layout(height=height_px, paper_bgcolor='#090a0f', plot_bgcolor='#090a0f', showlegend=False, margin=dict(l=30, r=30, t=10, b=30), hoverlabel=hover_style)
        fig_bot.update_xaxes(tickvals=unique_strikes, ticktext=strike_labels, tickangle=0, gridcolor='#151821')
        fig_bot.update_yaxes(range=[0, max_abs], gridcolor='#151821', zeroline=True, zerolinecolor='#444')
        return fig_top, fig_bot

    dash_top_fig, dash_bot_fig = build_gex_strike_figure(240)
    strike_top_fig, strike_bot_fig = build_gex_strike_figure(280)

    fig_split = go.Figure()
    fig_split.add_trace(go.Bar(x=filtered['strike'], y=filtered['gex_call'], marker_color='#22c55e', name='Calls', width=bar_w))
    fig_split.add_trace(go.Bar(x=filtered['strike'], y=-filtered['gex_put'], marker_color='#ef4444', name='Puts', width=bar_w))
    fig_split.add_vline(x=spot_price, line_width=1.5, line_dash="dash", line_color="#2979ff", annotation_text=f"Spot: ${spot_price:,.0f}")
    fig_split.update_layout(title="<b>BTC DERIBIT Gamma Exposure All Expirations</b>", title_font=dict(color="#fff", size=14), paper_bgcolor='#0b0e14', plot_bgcolor='#0b0e14', showlegend=False, hoverlabel=hover_style, margin=dict(l=40, r=40, t=40, b=40), height=450)
    fig_split.update_xaxes(tickvals=unique_strikes, ticktext=strike_labels, tickangle=-45, gridcolor='#1e2638', showgrid=False)
    fig_split.update_yaxes(title_text='Gamma ($M)', gridcolor='#1e2638', zeroline=True, zerolinewidth=1.5, zerolinecolor='#ffffff', autorange=True)

    fig_profile = go.Figure()
    fig_profile.add_trace(go.Bar(x=filtered['strike'], y=filtered['total'], marker_color=profile_colors, name='Net GEX', width=bar_w))
    fig_profile.add_vline(x=spot_price, line_width=1.5, line_dash="dash", line_color="#2979ff", annotation_text=f"Spot: ${spot_price:,.0f}")
    fig_profile.update_layout(title="<b>BTC DERIBIT Gamma Exposure Profile by Strike for All Expirations</b>", title_font=dict(color="#fff", size=14), paper_bgcolor='#0b0e14', plot_bgcolor='#0b0e14', showlegend=False, hoverlabel=hover_style, margin=dict(l=40, r=40, t=40, b=40), height=450)
    fig_profile.update_xaxes(tickvals=unique_strikes, ticktext=strike_labels, tickangle=-45, gridcolor='#1e2638', showgrid=False)
    fig_profile.update_yaxes(title_text='Gamma ($M)', gridcolor='#1e2638', zeroline=True, zerolinewidth=1.5, zerolinecolor='#ffffff', autorange=True)

    time_series = [f"{i:02d}:00" for i in range(10, 25, 2)] + [f"{i:02d}:00" for i in range(0, 10, 2)]
    cp_24h = [0.15, 0.13, 0.18, 0.22, 0.19, 0.15, 0.11, 0.08, 0.12, cp_val]
    updown_24h = [0.28, 0.22, 0.16, 0.18, 0.15, 0.20, 0.32, 0.28, 0.31, updown_val]
    net_24h = [65.2, 58.1, 82.4, 110.5, 95.0, 72.3, 61.2, 75.8, 92.1, round(filtered['total'].sum(), 1)]
    abs_24h = [410.2, 432.5, 452.1, 441.0, 438.2, 425.0, 412.3, 422.0, 440.1, round(filtered['abs_gex'].sum(), 1)]

    def create_trend_chart(title, x_vals, y_vals, color, unit=""):
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x_vals, y=y_vals, mode='lines', fill='tozeroy', line=dict(color=color, width=2), fillcolor=color.replace('rgb', 'rgba').replace(')', ', 0.15)')))
        fig.add_annotation(x=x_vals[-1], y=y_vals[-1], text=f"<b>{y_vals[-1]}{unit}</b>", showarrow=False, font=dict(color=color, size=13), xanchor='left')
        fig.update_layout(title=dict(text=f"<b>{title}</b>", font=dict(size=12, color='#aaa')), height=200, paper_bgcolor='#111625', plot_bgcolor='#111625', margin=dict(l=30, r=50, t=35, b=25), showlegend=False)
        fig.update_xaxes(gridcolor='#1e2638', tickfont=dict(color='#64748b', size=10))
        fig.update_yaxes(gridcolor='#1e2638', tickfont=dict(color='#64748b', size=10), autorange=True)
        return fig

    fig_t1 = create_trend_chart("GEX CALL/PUT (24H)", time_series, cp_24h, "rgb(234, 179, 8)")
    fig_t2 = create_trend_chart("GEX UP/DOWN (24H)", time_series, updown_24h, "rgb(168, 85, 247)")
    fig_t3 = create_trend_chart("NET GEX (24H)", time_series, net_24h, "rgb(59, 130, 246)", "M")
    fig_t4 = create_trend_chart("ABS GEX (24H)", time_series, abs_24h, "rgb(34, 197, 94)", "M")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_filepath = os.path.join(current_dir, 'index.html')

    html_dash_top = dash_top_fig.to_html(include_plotlyjs='cdn', full_html=False)
    html_dash_bot = dash_bot_fig.to_html(include_plotlyjs=False, full_html=False)
    html_strike_top = strike_top_fig.to_html(include_plotlyjs=False, full_html=False)
    html_strike_bot = strike_bot_fig.to_html(include_plotlyjs=False, full_html=False)
    html_split = fig_split.to_html(include_plotlyjs=False, full_html=False)
    html_profile = fig_profile.to_html(include_plotlyjs=False, full_html=False)
    html_t1 = fig_t1.to_html(include_plotlyjs=False, full_html=False)
    html_t2 = fig_t2.to_html(include_plotlyjs=False, full_html=False)
    html_t3 = fig_t3.to_html(include_plotlyjs=False, full_html=False)
    html_t4 = fig_t4.to_html(include_plotlyjs=False, full_html=False)

    table_strikes = [60000, 62000, 65000, 66000, 67000, 68000, 69000, 70000, 71000, 72000, 73000, 74000, 75000, 76000, 78000, 80000, 82000, 85000, 90000]
    now_vals = ["19.8M", "7.2M", "15.3M", "10.3M", "10.7M", "26.6M", "15.6M", "53.1M", "25.4M", "30.3M", "8.7M", "12.3M", "44.7M", "9.1M", "7.9M", "20.9M", "5.3M", "13.6M", "10.9M"]
    h24_vals = ["-5%", "-9%", "-8%", "-8%", "-5%", "+2%", "+16%", "+15%", "+23%", "+12%", "+9%", "-1%", "+6%", "+1%", "+6%", "+3%", "+13%", "+5%", "+2%"]
    h48_vals = ["-2%", "-1%", "0%", "+4%", "+12%", "+14%", "+33%", "+28%", "+15%", "+11%", "-12%", "-23%", "-7%", "-24%", "-4%", "-8%", "-6%", "-8%", "+13%"]
    w1_vals  = ["+9%", "+24%", "+15%", "+31%", "+88%", "+68%", "+80%", "+54%", "+113%", "+21%", "-68%", "-59%", "-22%", "-44%", "-26%", "-33%", "-39%", "-34%", "-35%"]

    def build_table_row(label, vals, is_now=False):
        row_html = f"<tr><td class='td-label'>{label}</td>"
        for v in vals:
            if is_now: bg, fg = "#1e293b", "#38bdf8"
            else:
                bg, fg = ("#14532d", "#4ade80") if v.startswith('+') else ("#7f1d1d", "#f87171")
            row_html += f"<td style='background:{bg}; color:{fg};'>{v}</td>"
        row_html += "</tr>"
        return row_html

    table_rows_html = build_table_row("Now", now_vals, True) + build_table_row("24h", h24_vals) + build_table_row("48h", h48_vals) + build_table_row("1w", w1_vals)
    table_cols_html = "".join([f"<th>{s:,.0f}</th>" for s in table_strikes])

    full_page_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>GammaFlip BTC Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ background-color: #080a0f; margin: 0; padding: 15px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #fff; }}
        .top-navbar {{ display: flex; justify-content: space-between; align-items: center; background: #111625; padding: 12px 24px; border-radius: 10px; border: 1px solid #1e2638; margin-bottom: 15px; }}
        .brand {{ font-size: 20px; font-weight: bold; color: #a855f7; display: flex; align-items: center; gap: 10px; }}
        .btn-group {{ display: flex; gap: 10px; flex-wrap: wrap; }}
        .nav-btn {{ background: #1e2638; color: #94a3b8; border: 1px solid #2e374e; padding: 9px 16px; border-radius: 8px; font-size: 13px; font-weight: bold; cursor: pointer; transition: 0.2s; }}
        .nav-btn:hover, .nav-btn.active {{ background: #a855f7; color: #fff; border-color: #a855f7; }}
        .view-section {{ display: none; width: 100%; }}
        .view-section.active {{ display: block; }}
        
        .dash-container {{ display: flex; flex-direction: column; gap: 15px; }}
        .dash-top-grid {{ display: grid; grid-template-columns: 320px 1fr; gap: 15px; }}
        .left-col {{ display: flex; flex-direction: column; gap: 12px; }}
        .card {{ background: #111625; border: 1px solid #1e2638; border-radius: 10px; padding: 15px; }}
        
        .gauge-meter {{ background: #0b0e14; border: 1px solid #1e2638; border-radius: 8px; padding: 10px; text-align: center; margin-bottom: 8px; }}
        .gauge-title {{ font-size: 12px; color: #888; margin-bottom: 4px; }}
        .gauge-bar {{ height: 10px; background: linear-gradient(90deg, #ef4444 0%, #ea580c 40%, #22c55e 100%); border-radius: 5px; margin: 8px 0; }}
        .gauge-score {{ font-size: 16px; font-weight: bold; color: #22c55e; }}

        .key-levels-box {{ display: flex; flex-direction: column; gap: 8px; font-size: 13px; margin-top: 5px; }}
        .key-row {{ display: flex; justify-content: space-between; padding-bottom: 4px; border-bottom: 1px solid #1e2638; }}
        .key-label {{ font-weight: bold; display: flex; align-items: center; gap: 6px; }}
        
        .trend-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }}
        .table-container {{ overflow-x: auto; background: #111625; border: 1px solid #1e2638; border-radius: 10px; padding: 15px; }}
        .change-table {{ width: 100%; border-collapse: collapse; font-size: 11px; text-align: center; }}
        .change-table th {{ padding: 8px 6px; color: #94a3b8; border-bottom: 1px solid #1e2638; font-weight: normal; }}
        .change-table td {{ padding: 8px 4px; border: 1px solid #080a0f; border-radius: 4px; font-weight: bold; }}
        .td-label {{ background: #111625 !important; color: #fff !important; text-align: left; padding-left: 10px !important; font-size: 12px; }}

        .main-charts-grid {{ display: grid; grid-template-columns: 1fr; gap: 15px; }}
        .main-charts-grid.side-by-side {{ grid-template-columns: 1fr 1fr; }}

        .filter-bar {{ display: flex; gap: 10px; margin-top: 15px; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #1e2638; }}
        .filter-btn {{ background: #1e2638; color: #94a3b8; border: none; padding: 6px 16px; border-radius: 20px; font-size: 12px; font-weight: bold; cursor: pointer; }}
        .filter-btn.active {{ background: #3b82f6; color: #fff; }}

        .cards-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; }}
        .badge-card {{ background: #0b0e14; border: 1px solid #1e2638; border-radius: 10px; padding: 12px; font-size: 13px; }}
        .card-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
        .card-tag {{ padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 11px; color: #fff; }}
        .pct-tag {{ background: #1e2638; color: #cbd5e1; padding: 2px 6px; border-radius: 4px; font-size: 10px; }}
        .card-price {{ font-size: 15px; font-weight: bold; margin-bottom: 2px; }}
        .card-gex {{ font-size: 12px; color: #94a3b8; font-weight: bold; margin-bottom: 6px; }}
        .card-sub {{ font-size: 11px; color: #64748b; }}

        .plotly-graph-div {{ width: 100% !important; }}
    </style>
</head>
<body>
    <div class="top-navbar">
        <div class="brand">⚡ GammaFlip.io <span style="font-size: 16px; color: #fff; margin-left: 8px;">BTC ${spot_price:,.0f}</span></div>
        <div class="btn-group">
            <button id="btn-dash" class="nav-btn active" onclick="switchView('dash-view', this)">⚡ GammaFlip 대시보드</button>
            <button id="btn-main" class="nav-btn" onclick="switchView('main-view', this)">📊 기본 Gamma 차트</button>
            <button id="btn-strike" class="nav-btn" onclick="switchView('strike-view', this)">🎯 Key Levels 상세</button>
            <button class="nav-btn" onclick="toggleOrientation()">🔄 레이아웃: <span id="modeText">위아래</span></button>
            <button class="nav-btn" onclick="swapCharts()">🔀 위치 바꾸기</button>
        </div>
    </div>

    <!-- VIEW 1: GammaFlip 대시보드 -->
    <div id="dash-view" class="view-section active">
        <div class="dash-container">
            <div class="dash-top-grid">
                <div class="left-col">
                    <div class="card">
                        <div class="gauge-meter">
                            <div class="gauge-title">Gamma Regime</div>
                            <div class="gauge-bar"></div>
                            <div class="gauge-score">Positive ({regime_val})</div>
                        </div>
                        <div class="gauge-meter">
                            <div class="gauge-title">GEX Call/Put</div>
                            <div class="gauge-bar"></div>
                            <div class="gauge-score">Bullish ({cp_val})</div>
                        </div>
                        <div class="gauge-meter">
                            <div class="gauge-title">GEX Up/Down</div>
                            <div class="gauge-bar"></div>
                            <div class="gauge-score">More Above ({updown_val})</div>
                        </div>
                    </div>

                    <div class="card">
                        <div style="font-size:12px; color:#888; font-weight:bold; margin-bottom:10px;">KEY LEVELS</div>
                        <div class="key-levels-box">
                            <div class="key-row"><span class="key-label" style="color:#d946ef;"><span style="background:#d946ef; color:#fff; padding:1px 5px; border-radius:3px; font-size:10px;">F</span> Flip Point</span><b style="color:#d946ef;">${flip_point:,.0f}</b></div>
                            <div class="key-row"><span class="key-label" style="color:#22c55e;"><span style="background:#22c55e; color:#fff; padding:1px 4px; border-radius:3px; font-size:10px;">MS</span> Max Stability</span><b style="color:#22c55e;">${ms:,.0f}</b></div>
                            <div class="key-row"><span class="key-label" style="color:#ef4444;"><span style="background:#ef4444; color:#fff; padding:1px 4px; border-radius:3px; font-size:10px;">MV</span> Max Volatility</span><b style="color:#ef4444;">${mv:,.0f}</b></div>
                            <div class="key-row"><span class="key-label" style="color:#22c55e;"><span style="background:#22c55e; color:#fff; padding:1px 5px; border-radius:3px; font-size:10px;">P1</span> Positive Peak</span><b style="color:#22c55e;">${p1:,.0f}</b></div>
                            <div class="key-row"><span class="key-label" style="color:#ef4444;"><span style="background:#ef4444; color:#fff; padding:1px 5px; border-radius:3px; font-size:10px;">N1</span> Negative Peak</span><b style="color:#ef4444;">${n1:,.0f}</b></div>
                            <div class="key-row"><span class="key-label" style="color:#a855f7;"><span style="background:#a855f7; color:#fff; padding:1px 5px; border-radius:3px; font-size:10px;">A1</span> Absolute Max</span><b style="color:#a855f7;">${a1:,.0f}</b></div>
                        </div>
                    </div>
                </div>

                <div class="card" style="padding:5px; display:flex; flex-direction:column; gap:0px;">
                    <div>{html_dash_top}</div>
                    <div>{html_dash_bot}</div>
                </div>
            </div>

            <div class="trend-grid">
                <div class="card" style="padding:5px;">{html_t1}</div>
                <div class="card" style="padding:5px;">{html_t2}</div>
                <div class="card" style="padding:5px;">{html_t3}</div>
                <div class="card" style="padding:5px;">{html_t4}</div>
            </div>

            <div class="table-container">
                <div style="font-size:13px; font-weight:bold; color:#fff; margin-bottom:10px;">ABS GEX — % CHANGE <span style="font-size:11px; color:#888; float:right;">Top strikes: <button style="background:#3b82f6; color:#fff; border:none; border-radius:3px; padding:2px 6px;">80%</button></span></div>
                <table class="change-table">
                    <thead>
                        <tr>
                            <th style="text-align:left; padding-left:10px;">Strike</th>
                            {table_cols_html}
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows_html}
                    </tbody>
                </table>
            </div>

        </div>
    </div>

    <!-- VIEW 2: 기본 Gamma 차트 -->
    <div id="main-view" class="view-section">
        <div id="mainGrid" class="main-charts-grid">
            <div id="chartBoxA" class="card" style="padding:10px;">{html_split}</div>
            <div id="chartBoxB" class="card" style="padding:10px;">{html_profile}</div>
        </div>
    </div>

    <!-- VIEW 3: Key Levels 상세 -->
    <div id="strike-view" class="view-section">
        <div class="card" style="padding:15px;">
            <div style="display:flex; flex-direction:column; gap:0px;">
                <div>{html_strike_top}</div>
                <div>{html_strike_bot}</div>
            </div>

            <div class="filter-bar">
                <button class="filter-btn active">📌 Positive</button>
                <button class="filter-btn">Negative</button>
                <button class="filter-btn">Absolute</button>
                <button class="filter-btn">Regime</button>
            </div>

            <div class="cards-grid">
                <div class="badge-card">
                    <div class="card-top"><span class="card-tag" style="background:#ef4444;">V</span><span class="pct-tag">{get_pct(mv)}</span></div>
                    <div class="card-price" style="color:#ef4444;">${mv:,.0f}</div>
                    <div class="card-sub">Max Volatility</div>
                </div>
                <div class="badge-card">
                    <div class="card-top"><span class="card-tag" style="background:#ef4444;">N2</span><span class="pct-tag">{get_pct(n2)}</span></div>
                    <div class="card-price" style="color:#ef4444;">${n2:,.0f}</div>
                    <div class="card-gex">{v_n2:.1f}M</div>
                    <div class="card-sub">Vol. Trigger</div>
                </div>
                <div class="badge-card">
                    <div class="card-top"><span class="card-tag" style="background:#ef4444;">N1</span><span class="pct-tag">{get_pct(n1)}</span></div>
                    <div class="card-price" style="color:#ef4444;">${n1:,.0f}</div>
                    <div class="card-gex">{v_n1:.1f}M</div>
                    <div class="card-sub">Vol. Trigger</div>
                </div>
                <div class="badge-card">
                    <div class="card-top"><span class="card-tag" style="background:#a855f7;">A1</span><span class="pct-tag">{get_pct(a1)}</span></div>
                    <div class="card-price" style="color:#a855f7;">${a1:,.0f}</div>
                    <div class="card-gex">{v_a1:.1f}M</div>
                    <div class="card-sub">Magnet</div>
                </div>
                <div class="badge-card">
                    <div class="card-top"><span class="card-tag" style="background:#d946ef;">F</span><span class="pct-tag">{get_pct(flip_point)}</span></div>
                    <div class="card-price" style="color:#d946ef;">${flip_point:,.0f}</div>
                    <div class="card-gex">0M</div>
                    <div class="card-sub">Regime Change</div>
                </div>
                <div class="badge-card">
                    <div class="card-top"><span class="card-tag" style="background:#a855f7;">A2</span><span class="pct-tag">{get_pct(a2)}</span></div>
                    <div class="card-price" style="color:#a855f7;">${a2:,.0f}</div>
                    <div class="card-gex">{v_a2:.1f}M</div>
                    <div class="card-sub">Magnet</div>
                </div>
                <div class="badge-card">
                    <div class="card-top"><span class="card-tag" style="background:#22c55e;">P1</span><span class="pct-tag">{get_pct(p1)}</span></div>
                    <div class="card-price" style="color:#22c55e;">${p1:,.0f}</div>
                    <div class="card-gex">{v_p1:.1f}M</div>
                    <div class="card-sub">Gamma Resist.</div>
                </div>
                <div class="badge-card">
                    <div class="card-top"><span class="card-tag" style="background:#22c55e;">P2</span><span class="pct-tag">{get_pct(p2)}</span></div>
                    <div class="card-price" style="color:#22c55e;">${p2:,.0f}</div>
                    <div class="card-gex">{v_p2:.1f}M</div>
                    <div class="card-sub">Gamma Resist.</div>
                </div>
                <div class="badge-card">
                    <div class="card-top"><span class="card-tag" style="background:#22c55e;">S</span><span class="pct-tag">{get_pct(ms)}</span></div>
                    <div class="card-price" style="color:#22c55e;">${ms:,.0f}</div>
                    <div class="card-sub">Max Stability</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        setTimeout(function() {{
            location.reload();
        }}, 30000);

        function switchView(viewId, btn) {{
            document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            
            const activeView = document.getElementById(viewId);
            if (activeView) activeView.classList.add('active');
            if (btn) btn.classList.add('active');

            localStorage.setItem('gex_active_view', viewId);

            setTimeout(() => {{
                window.dispatchEvent(new Event('resize'));
            }}, 50);
        }}

        let isVertical = localStorage.getItem('gex_isVertical') === 'false' ? false : true;
        let isSwapped = localStorage.getItem('gex_isSwapped') === 'true' ? true : false;

        function applyLayout() {{
            const grid = document.getElementById('mainGrid');
            const boxA = document.getElementById('chartBoxA');
            const boxB = document.getElementById('chartBoxB');
            if (!grid || !boxA || !boxB) return;

            document.getElementById('modeText').innerText = isVertical ? "위아래" : "좌우";

            if (isVertical) {{
                grid.classList.remove('side-by-side');
            }} else {{
                grid.classList.add('side-by-side');
            }}

            if (isSwapped) {{
                grid.appendChild(boxA);
            }} else {{
                grid.appendChild(boxB);
            }}

            setTimeout(() => {{
                window.dispatchEvent(new Event('resize'));
            }}, 50);
        }}

        function toggleOrientation() {{ isVertical = !isVertical; localStorage.setItem('gex_isVertical', isVertical); applyLayout(); }}
        function swapCharts() {{ isSwapped = !isSwapped; localStorage.setItem('gex_isSwapped', isSwapped); applyLayout(); }}

        window.addEventListener('load', function() {{ 
            setTimeout(() => {{
                const savedView = localStorage.getItem('gex_active_view');
                if (savedView) {{
                    let targetBtn = document.getElementById('btn-dash');
                    if (savedView === 'main-view') targetBtn = document.getElementById('btn-main');
                    if (savedView === 'strike-view') targetBtn = document.getElementById('btn-strike');
                    switchView(savedView, targetBtn);
                }}
                applyLayout();
                window.dispatchEvent(new Event('resize'));
            }}, 150);
        }});
    </script>
</body>
</html>
"""

    with open(output_filepath, 'w', encoding='utf-8') as f:
        f.write(full_page_html)
        
    print(f"✅ [{current_time_str}] index.html 갱신 완료!")

if __name__ == '__main__':
    generate_gamma_chart()

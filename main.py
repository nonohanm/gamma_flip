import os
import json
import math
import requests
import pandas as pd
from datetime import datetime, timezone

def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def calculate_bs_gamma(S, K, T, r=0.0, sigma=0.6):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_pdf(d1) / (S * sigma * math.sqrt(T))

def generate_json_data():
    current_time_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"[{current_time_str}] Deribit 데이터 수집 및 JSON 변환 시작...")
    
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
    if df.empty:
        print("❌ 처리할 옵션 데이터가 없습니다.")
        return

    calls = df[df['option_type'] == 'call'].groupby('strike')['gex'].sum().reset_index()
    puts = df[df['option_type'] == 'put'].groupby('strike')['gex'].sum().reset_index()
    
    merged = pd.merge(calls, puts, on='strike', how='outer', suffixes=('_call', '_put')).fillna(0)
    merged['total'] = merged['gex_call'] - merged['gex_put']
    
    min_strike = spot_price * 0.70
    max_strike = spot_price * 1.30
    filtered = merged[(merged['strike'] >= min_strike) & (merged['strike'] <= max_strike)].sort_values('strike').reset_index(drop=True)

    # JSON으로 내보낼 최종 페이로드 구성
    payload = {
        "updated_at": current_time_str,
        "spot_price": spot_price,
        "strikes": filtered['strike'].tolist(),
        "net_gex": filtered['total'].round(2).tolist()
    }

    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_filepath = os.path.join(current_dir, 'data.json')

    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)
        
    print(f"✅ [{current_time_str}] data.json 생성 완료!")

if __name__ == '__main__':
    generate_json_data()

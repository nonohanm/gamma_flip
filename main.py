import os
import json
import requests
import pandas as pd
from datetime import datetime, timezone

def generate_data():
    # 1. Deribit API 호출 (예시)
    try:
        index_url = "https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd"
        spot_price = requests.get(index_url, timeout=10).json()['result']['index_price']
        
        summary_url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"
        summary_res = requests.get(summary_url, timeout=10).json()['result']
    except Exception as e:
        print(f"API 실패: {e}")
        return

    # 2. 데이터 가공 (여기서 원하는 지표 계산)
    # 예시로 간단한 구조만 담습니다.
    data_payload = {
        "updated_at": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        "spot_price": spot_price,
        "strikes": [60000, 65000, 70000, 75000, 80000],
        "net_gex": [15.5, -10.2, 45.1, 20.3, -5.4]
    }

    # 3. data.json 파일로 저장
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, 'data.json')
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data_payload, f, ensure_ascii=False, indent=4)
    
    print("✅ data.json 생성 완료!")

if __name__ == '__main__':
    generate_data()

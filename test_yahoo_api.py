#!/usr/bin/env python3
import requests
import json
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://finance.yahoo.com/',
}

def test_chart_api():
    url = 'https://query2.finance.yahoo.com/v8/finance/chart/SLV?interval=1m&range=1d&includePrePost=true'
    try:
        session = requests.Session()
        response = session.get(url, headers=HEADERS, timeout=15)
        print(f'Chart API Status: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            result = data.get('chart', {}).get('result', [])
            if result:
                meta = result[0].get('meta', {})
                print('Current Trading Period:', json.dumps(meta.get('currentTradingPeriod'), indent=2))
                # Check timestamps
                timestamps = result[0].get('timestamp', [])
                print(f'Number of data points: {len(timestamps)}')
                if timestamps:
                    print(f'Last timestamp: {time.ctime(timestamps[-1])}')
    except Exception as e:
        print(f'Chart API Error: {e}')

def test_quote_api():
    url = 'https://query1.finance.yahoo.com/v7/finance/quote?symbols=SLV'
    try:
        session = requests.Session()
        response = session.get(url, headers=HEADERS, timeout=15)
        print(f'Quote API Status: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            quote = data.get('quoteResponse', {}).get('result', [])
            if quote:
                print('Available keys:', list(quote[0].keys()))
    except Exception as e:
        print(f'Quote API Error: {e}')

if __name__ == '__main__':
    test_chart_api()
    print()
    test_quote_api()

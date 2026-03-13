#!/usr/bin/env python3
"""
SLV ETF 数据采集模块 V2
数据源优先级：
1. NASDAQ API - 盘前/盘中/盘后实时价格（主要来源）
2. Yahoo Finance API - 夜盘/延长时间价格（北京时间8-16点优先）
3. Qveris - 最后备用（当以上都失败时）
"""

import requests
import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging
import os

# 导入新的Yahoo Finance API模块
from yahoo_finance_api import YahooFinanceAPI, DataSourceStatus, is_beijing_extended_hours

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class QverisClient:
    """Qveris API 客户端 - 最后备用数据源"""

    BASE_URL = "https://qveris.ai/api/v1"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('QVERIS_API_KEY', '')
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def get_quote(self, symbol: str = "SLV") -> Optional[Dict]:
        """
        通过 Qveris 获取报价（最后备用）
        使用 TwelveData Quote 工具
        """
        try:
            tool_id = "twelvedata.quote.retrieve.v1.affbefe3"
            search_id = "qveris_fallback"

            response = requests.post(
                f"{self.BASE_URL}/tools/execute",
                headers=self.headers,
                params={"tool_id": tool_id},
                json={
                    "search_id": search_id,
                    "parameters": {"symbol": symbol},
                    "max_response_size": 20480
                },
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    data = result.get('result', {}).get('data', {})
                    return {
                        'symbol': symbol,
                        'last_price': float(data.get('close', 0)) if data.get('close') else None,
                        'net_change': float(data.get('change', 0)) if data.get('change') else None,
                        'change_pct': float(data.get('percent_change', 0)) if data.get('percent_change') else None,
                        'volume': int(data.get('volume', 0)) if data.get('volume') else None,
                        'open': float(data.get('open', 0)) if data.get('open') else None,
                        'high': float(data.get('high', 0)) if data.get('high') else None,
                        'low': float(data.get('low', 0)) if data.get('low') else None,
                        'previous_close': float(data.get('previous_close', 0)) if data.get('previous_close') else None,
                        'data_source': 'qveris_twelvedata',
                        'market_status': 'unknown'
                    }
        except Exception as e:
            logger.error(f"Qveris get_quote error: {e}")
        return None


class SLVDataFetcher:
    """SLV数据采集器 - 多数据源优先级管理"""

    BASE_URL = "https://api.nasdaq.com/api/quote/SLV"
    HEADERS = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh-Hans;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Origin': 'https://www.nasdaq.com',
        'Referer': 'https://www.nasdaq.com/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15'
    }

    def __init__(self, data_dir: str = "."):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.data_dir = Path(data_dir)
        self.historical_file = self.data_dir / "slv_daily_data.csv"
        self.qveris = QverisClient()
        self.yahoo_api = YahooFinanceAPI()

    def get_intraday_data(self) -> Optional[pd.DataFrame]:
        """获取NASDAQ日内实时数据"""
        url = f"{self.BASE_URL}/chart"
        params = {'assetclass': 'etf', 'charttype': 'rs'}

        try:
            logger.info("Fetching NASDAQ intraday data...")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data.get('data') or not data['data'].get('chart'):
                logger.warning("No intraday data available")
                return None

            chart_data = data['data']['chart']
            records = []

            for item in chart_data:
                ts_ms = item.get('x')
                if ts_ms:
                    dt = datetime.fromtimestamp(ts_ms / 1000)
                    record = {
                        'datetime': dt,
                        'timestamp': ts_ms,
                        'price': float(item.get('y', 0)),
                        'volume': float(item.get('w', 0)),
                        'time_str': item.get('z', {}).get('time'),
                        'prev_close': float(item.get('z', {}).get('prevCls', 0).replace('$', '')) if item.get('z', {}).get('prevCls') else None
                    }
                    records.append(record)

            df = pd.DataFrame(records)
            df = df.sort_values('datetime').reset_index(drop=True)
            logger.info(f"Got {len(df)} intraday records")
            return df

        except Exception as e:
            logger.error(f"Error fetching intraday data: {e}")
            return None

    def get_yfinance_data(self) -> Optional[Dict]:
        """
        通过 yfinance 直接获取夜盘/延长时间数据
        优先级：NASDAQ 之后的第二数据源
        """
        try:
            import yfinance as yf
            slv = yf.Ticker('SLV')

            # 获取股票信息（包含盘前盘后）
            info = slv.info

            # 获取历史数据以计算夜盘高低点
            hist = slv.history(period="5d", interval="1h", prepost=True)

            extended_hours_high = None
            extended_hours_low = None
            pre_market_price = None
            post_market_price = None

            if not hist.empty:
                # 分离延长时间数据（Volume=0 或 NaN）
                extended_data = hist[hist['Volume'].isna() | (hist['Volume'] == 0)]
                regular_data = hist[hist['Volume'] > 0]

                if not extended_data.empty:
                    extended_hours_high = float(extended_data['High'].max())
                    extended_hours_low = float(extended_data['Low'].min())

                    # 获取最新延长时间价格（可能是盘前或盘后）
                    latest_extended = extended_data.iloc[-1]
                    latest_price = float(latest_extended['Close'])

                    # 判断是盘前还是盘后
                    if not regular_data.empty:
                        last_regular_time = regular_data.index[-1]
                        if extended_data.index[-1] > last_regular_time:
                            # 在常规交易时间之后 = 盘后
                            post_market_price = latest_price
                        elif extended_data.index[-1] < regular_data.index[0]:
                            # 在常规交易时间之前 = 盘前
                            pre_market_price = latest_price
                        else:
                            # 跨时间段，根据时间点判断
                            latest_hour = extended_data.index[-1].hour
                            if latest_hour < 9 or (latest_hour == 9 and extended_data.index[-1].minute < 30):
                                pre_market_price = latest_price
                            else:
                                post_market_price = latest_price
                    else:
                        # 只有延长时间数据
                        pre_market_price = latest_price

            return {
                'post_market_price': post_market_price or (info.get('postMarketPrice')),
                'pre_market_price': pre_market_price or (info.get('preMarketPrice')),
                'regular_price': info.get('regularMarketPrice'),
                'previous_close': info.get('regularMarketPreviousClose'),
                'extended_hours_high': extended_hours_high,
                'extended_hours_low': extended_hours_low,
                'data_source': 'yfinance_direct',
                'is_extended_hours': info.get('postMarketPrice') is not None or info.get('preMarketPrice') is not None
            }

        except Exception as e:
            logger.error(f"Error fetching yfinance data: {e}")
            return None

    def get_current_quote(self) -> Optional[Dict]:
        """
        获取实时报价
        数据源优先级：
        1. 北京时间 8:00-16:00 期间，优先使用 Yahoo Finance API 获取夜盘数据
        2. NASDAQ API（盘前/盘中/盘后实时价格）- 主要来源
        3. Yahoo Finance API（夜盘价格）- 补充延长时间数据
        4. Qveris（最后备用）- 当以上都失败时使用
        
        返回数据包含以下标记：
        - is_extended_hours: 是否为夜盘价格
        - price_type: 价格类型 (regular_hours/pre_market/post_market/extended_hours)
        - yahoo_fallback: 是否使用了雅虎数据作为fallback
        - yahoo_status: 雅虎数据源状态
        """
        quote = None
        yahoo_fallback = False
        yahoo_status = None
        
        # 判断是否为北京时间延长时间 (8:00-16:00)
        is_bj_extended = is_beijing_extended_hours()
        logger.info(f"Beijing extended hours (8-16): {is_bj_extended}")

        # 1. 北京时间延长时间优先使用 Yahoo Finance API
        if is_bj_extended:
            logger.info("Beijing extended hours detected, trying Yahoo Finance API first...")
            yahoo_data = self.yahoo_api.get_extended_hours_price("SLV")
            yahoo_status = yahoo_data.source_status.value
            
            if yahoo_data.source_status == DataSourceStatus.SUCCESS and yahoo_data.last_price:
                quote = {
                    'symbol': 'SLV',
                    'name': 'iShares Silver Trust',
                    'last_price': yahoo_data.last_price,
                    'net_change': yahoo_data.net_change,
                    'change_pct': yahoo_data.change_pct,
                    'volume': yahoo_data.volume,
                    'bid': None,
                    'ask': None,
                    'timestamp': yahoo_data.timestamp.isoformat() if yahoo_data.timestamp else None,
                    'is_realtime': True,
                    'price_source': 'yahoo_api_extended_hours',
                    'market_status': 'extended_hours',
                    'is_extended_hours': yahoo_data.is_extended_hours,
                    'price_type': yahoo_data.price_type.value,
                    'pre_market_price': yahoo_data.pre_market_price,
                    'post_market_price': yahoo_data.post_market_price,
                    'extended_hours_high': yahoo_data.extended_hours_high,
                    'extended_hours_low': yahoo_data.extended_hours_low,
                    'previous_close': yahoo_data.previous_close,
                    'yahoo_fallback': False,
                    'yahoo_status': yahoo_status,
                }
                logger.info(f"Yahoo API success (priority): ${quote['last_price']}, type={quote['price_type']}")
            else:
                logger.warning(f"Yahoo API failed: {yahoo_status}, will try NASDAQ...")
                yahoo_fallback = True

        # 2. 非延长时间或 Yahoo 失败时，尝试 NASDAQ API
        if not quote:
            logger.info("Trying NASDAQ API...")
            quote = self._get_nasdaq_quote()

            if quote:
                logger.info(f"NASDAQ success: ${quote['last_price']}")
                
                # 获取 Yahoo Finance 夜盘数据作为补充
                logger.info("Fetching Yahoo Finance extended hours data as supplement...")
                yahoo_data = self.yahoo_api.get_extended_hours_price("SLV")
                yahoo_status = yahoo_data.source_status.value
                
                if yahoo_data.source_status == DataSourceStatus.SUCCESS:
                    # 补充夜盘数据到 quote
                    quote['pre_market_price'] = yahoo_data.pre_market_price
                    quote['post_market_price'] = yahoo_data.post_market_price
                    quote['extended_hours_high'] = yahoo_data.extended_hours_high
                    quote['extended_hours_low'] = yahoo_data.extended_hours_low
                    quote['is_extended_hours'] = yahoo_data.is_extended_hours
                    quote['price_type'] = yahoo_data.price_type.value
                    quote['yahoo_fallback'] = yahoo_fallback
                    quote['yahoo_status'] = yahoo_status
                    
                    # 如果当前是延长时间，且 NASDAQ 数据较旧，使用 Yahoo 的最新价格
                    if yahoo_data.is_extended_hours and yahoo_data.last_price:
                        if quote.get('volume', 0) == 0 or yahoo_data.price_type.value in ['post_market', 'pre_market']:
                            logger.info(f"Market in extended hours, using Yahoo price: ${yahoo_data.last_price}")
                            quote['last_price'] = yahoo_data.last_price
                            quote['net_change'] = yahoo_data.net_change
                            quote['change_pct'] = yahoo_data.change_pct
                            quote['market_status'] = 'extended_hours'
                            quote['price_source'] = 'yahoo_api_extended_hours'
                    
                    logger.info(f"Yahoo supplement: pre=${yahoo_data.pre_market_price}, post=${yahoo_data.post_market_price}")
                else:
                    quote['is_extended_hours'] = False
                    quote['price_type'] = 'regular_hours'
                    quote['yahoo_fallback'] = yahoo_fallback
                    quote['yahoo_status'] = yahoo_status
        else:
            # 已经在延长时间模式获取到Yahoo数据，补充NASDAQ作为备选
            logger.info("Fetching NASDAQ data as supplement...")
            nasdaq_quote = self._get_nasdaq_quote()
            if nasdaq_quote:
                quote['nasdaq_backup_price'] = nasdaq_quote.get('last_price')

        # 3. 如果 NASDAQ 失败且之前没有获取到 Yahoo 数据，尝试 Yahoo 作为备选
        if not quote:
            logger.warning("NASDAQ API failed, trying Yahoo Finance as fallback...")
            yahoo_data = self.yahoo_api.get_extended_hours_price("SLV")
            yahoo_status = yahoo_data.source_status.value
            
            if yahoo_data.source_status == DataSourceStatus.SUCCESS and yahoo_data.last_price:
                quote = {
                    'symbol': 'SLV',
                    'name': 'iShares Silver Trust',
                    'last_price': yahoo_data.last_price,
                    'net_change': yahoo_data.net_change,
                    'change_pct': yahoo_data.change_pct,
                    'volume': yahoo_data.volume,
                    'bid': None,
                    'ask': None,
                    'timestamp': yahoo_data.timestamp.isoformat() if yahoo_data.timestamp else None,
                    'is_realtime': True,
                    'price_source': 'yahoo_api_fallback',
                    'market_status': 'extended_hours' if yahoo_data.is_extended_hours else 'regular_hours',
                    'is_extended_hours': yahoo_data.is_extended_hours,
                    'price_type': yahoo_data.price_type.value,
                    'pre_market_price': yahoo_data.pre_market_price,
                    'post_market_price': yahoo_data.post_market_price,
                    'extended_hours_high': yahoo_data.extended_hours_high,
                    'extended_hours_low': yahoo_data.extended_hours_low,
                    'previous_close': yahoo_data.previous_close,
                    'yahoo_fallback': True,
                    'yahoo_status': yahoo_status,
                }
                logger.info(f"Using Yahoo API fallback: ${quote['last_price']}")

        # 4. 最后备用：Qveris
        if not quote:
            logger.warning("All primary sources failed, trying Qveris as fallback...")
            qveris_data = self.qveris.get_quote("SLV")
            if qveris_data and qveris_data.get('last_price'):
                quote = qveris_data
                quote['is_extended_hours'] = False
                quote['price_type'] = 'unknown'
                quote['yahoo_fallback'] = True
                quote['yahoo_status'] = yahoo_status or 'all_failed'
                logger.info(f"Using Qveris fallback: ${quote['last_price']}")

        if not quote:
            logger.error("All data sources failed!")
            # 返回一个带有错误信息的空结构
            return {
                'symbol': 'SLV',
                'name': 'iShares Silver Trust',
                'last_price': None,
                'price_source': 'all_failed',
                'is_extended_hours': False,
                'price_type': 'unknown',
                'yahoo_fallback': True,
                'yahoo_status': yahoo_status or 'all_failed',
                'error': 'All data sources failed'
            }

        return quote

    def _get_nasdaq_quote(self) -> Optional[Dict]:
        """从 NASDAQ API 获取实时报价"""
        url = f"{self.BASE_URL}/info"
        params = {'assetclass': 'etf'}

        try:
            response = self.session.get(url, params=params, timeout=30)
            data = response.json()

            if data.get('data') and data['data'].get('primaryData'):
                primary = data['data']['primaryData']
                return {
                    'symbol': 'SLV',
                    'name': data['data'].get('companyName', 'iShares Silver Trust'),
                    'last_price': self._parse_price(primary.get('lastSalePrice')),
                    'net_change': self._parse_price(primary.get('netChange')),
                    'change_pct': self._parse_pct(primary.get('percentageChange')),
                    'volume': int(primary.get('volume', '0').replace(',', '')) if primary.get('volume') else None,
                    'bid': self._parse_price(primary.get('bidPrice')),
                    'ask': self._parse_price(primary.get('askPrice')),
                    'timestamp': primary.get('lastTradeTimestamp'),
                    'is_realtime': primary.get('isRealTime', False),
                    'price_source': 'nasdaq',
                    'market_status': 'regular_hours'
                }
        except Exception as e:
            logger.warning(f"NASDAQ API error: {e}")
        return None

    def load_historical_data(self) -> pd.DataFrame:
        """加载本地历史日K数据"""
        if not self.historical_file.exists():
            logger.warning(f"Historical data file not found: {self.historical_file}")
            return pd.DataFrame()

        try:
            df = pd.read_csv(self.historical_file)
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date').reset_index(drop=True)
            logger.info(f"Loaded {len(df)} historical records")
            return df
        except Exception as e:
            logger.error(f"Error loading historical data: {e}")
            return pd.DataFrame()

    def _parse_price(self, price_str: str) -> Optional[float]:
        """解析价格字符串"""
        if not price_str:
            return None
        try:
            return float(price_str.replace('$', '').replace(',', ''))
        except:
            return None

    def _parse_pct(self, pct_str: str) -> Optional[float]:
        """解析百分比字符串"""
        if not pct_str:
            return None
        try:
            return float(pct_str.replace('%', '').replace('+', ''))
        except:
            return None

    def get_analysis_data(self) -> Dict:
        """获取完整的分析数据"""
        hist_df = self.load_historical_data()
        quote = self.get_current_quote()
        intraday = self.get_intraday_data()

        result = {
            "symbol": "SLV",
            "name": "iShares Silver Trust",
            "data_timestamp": datetime.now().isoformat(),
            "current_quote": quote,
            "historical_daily": [],
            "intraday": []
        }

        if not hist_df.empty:
            for _, row in hist_df.tail(60).iterrows():
                result["historical_daily"].append({
                    "date": row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else None,
                    "open": row.get('Open'),
                    "high": row.get('High'),
                    "low": row.get('Low'),
                    "close": row.get('Close'),
                    "volume": int(row.get('Volume', 0)) if pd.notna(row.get('Volume')) else 0
                })

        if intraday is not None and not intraday.empty:
            result["intraday"] = intraday.to_dict('records')

        return result

    def get_data_for_technical_analysis(self) -> Dict:
        """获取技术分析所需的数据格式"""
        data = self.get_analysis_data()
        hist = data.get("historical_daily", [])
        quote = data.get("current_quote", {})

        if not hist:
            return {}

        latest = hist[-1] if hist else {}

        if quote and quote.get('last_price'):
            current_data = {
                "date": datetime.now().strftime('%Y-%m-%d'),
                "open": quote.get('last_price', latest.get('close', 0)) - (quote.get('net_change', 0) or 0),
                "high": max(quote.get('last_price', 0), latest.get('high', 0)),
                "low": min(quote.get('last_price', float('inf')), latest.get('low', float('inf'))),
                "close": quote.get('last_price'),
                "volume": quote.get('volume', latest.get('volume', 0))
            }
        else:
            current_data = latest

        return {
            "symbol": "SLV",
            "name": "iShares Silver Trust",
            "current_data": current_data,
            "historical_data": hist[-60:] if len(hist) > 60 else hist,
            "market_context": {
                "dxy": None,
                "vix": None,
                "gold_silver_ratio": None
            }
        }

    def get_data_for_sentiment_analysis(self) -> Dict:
        """获取市场情绪分析所需的数据格式"""
        data = self.get_analysis_data()
        hist = data.get("historical_daily", [])
        quote = data.get("current_quote", {})

        if not hist:
            return {}

        latest = hist[-1]
        prev = hist[-2] if len(hist) > 1 else latest

        current_price = quote.get('last_price') or latest.get('close', 0)
        current_volume = quote.get('volume') or latest.get('volume', 0)
        net_change = quote.get('net_change', 0)
        change_pct = quote.get('change_pct', 0)

        prev_close = prev.get('close', current_price)

        if not net_change and current_price and prev_close:
            net_change = current_price - prev_close
            change_pct = (net_change / prev_close * 100) if prev_close else 0

        closes = [h.get('close') for h in hist if h.get('close')]
        high_52w = max(closes) if closes else current_price
        low_52w = min(closes) if closes else current_price
        price_position = ((current_price - low_52w) / (high_52w - low_52w)) if (high_52w - low_52w) > 0 else 0.5

        volumes = [h.get('volume', 0) for h in hist[-20:] if h.get('volume')]
        avg_volume = sum(volumes) / len(volumes) if volumes else 1

        return {
            "price_data": {
                "current_price": round(current_price, 2) if current_price else None,
                "price_change_1d": round(net_change, 2),
                "price_change_pct": round(change_pct, 2),
                "volume": current_volume,
                "volume_vs_avg": round(current_volume / avg_volume, 2) if avg_volume else 1.0,
                "high_52w": round(high_52w, 2),
                "low_52w": round(low_52w, 2),
                "price_position": round(price_position, 2)
            },
            "correlated_markets": {
                "silver_futures": {"price": None, "change_pct": None},
                "gold_futures": {"price": None, "change_pct": None},
                "dxy": {"value": None, "change_pct": None},
                "ten_year_yield": {"value": None, "change_pct": None}
            },
            "gold_silver_ratio": {
                "current": None,
                "historical_mean": 65.0,
                "historical_range": [50, 85],
                "percentile": None
            },
            "fear_greed": {
                "index_value": None,
                "category": None,
                "previous_day": None,
                "trend": None
            },
            "news_sentiment": {
                "bullish_count": None,
                "bearish_count": None,
                "neutral_count": None,
                "sentiment_score": None,
                "key_topics": []
            },
            "fund_flows": {
                "etf_inflow_1d": None,
                "etf_inflow_5d": None,
                "institutional_holdings_change": None,
                "retail_sentiment": None
            }
        }


def test_fetcher():
    """测试数据采集器"""
    fetcher = SLVDataFetcher(data_dir="/Users/lzy/pro/slv")

    print("=" * 60)
    print("测试SLV数据采集器 V2")
    print("数据源优先级: NASDAQ > Yahoo Finance > Qveris")
    print("=" * 60)

    # 获取实时报价
    print("\n1. 获取实时报价...")
    quote = fetcher.get_current_quote()
    if quote:
        print(f"✓ 实时报价:")
        print(f"  当前价: ${quote['last_price']}")
        print(f"  涨跌: {quote.get('net_change', 'N/A')}")
        print(f"  涨跌幅: {quote.get('change_pct', 'N/A')}%")
        print(f"  成交量: {quote.get('volume', 'N/A')}")
        print(f"  数据源: {quote.get('price_source', 'N/A')}")
        print(f"  市场状态: {quote.get('market_status', 'N/A')}")
        print(f"  是否夜盘: {quote.get('is_extended_hours', False)}")
        print(f"  价格类型: {quote.get('price_type', 'N/A')}")
        print(f"  Yahoo Fallback: {quote.get('yahoo_fallback', False)}")
        print(f"  Yahoo 状态: {quote.get('yahoo_status', 'N/A')}")
        if quote.get('pre_market_price'):
            print(f"  盘前价: ${quote['pre_market_price']}")
        if quote.get('post_market_price'):
            print(f"  盘后价: ${quote['post_market_price']}")
        if quote.get('extended_hours_high'):
            print(f"  夜盘最高: ${quote['extended_hours_high']}")
        if quote.get('extended_hours_low'):
            print(f"  夜盘最低: ${quote['extended_hours_low']}")
    else:
        print("✗ 获取实时报价失败")

    # 测试 Yahoo Finance 直接获取
    print("\n2. 测试 Yahoo Finance 夜盘数据...")
    yf_data = fetcher.get_yfinance_data()
    if yf_data:
        print(f"✓ Yahoo Finance:")
        print(f"  常规价: ${yf_data.get('regular_price')}")
        print(f"  盘前价: ${yf_data.get('pre_market_price')}")
        print(f"  盘后价: ${yf_data.get('post_market_price')}")
        print(f"  夜盘最高: ${yf_data.get('extended_hours_high')}")
        print(f"  夜盘最低: ${yf_data.get('extended_hours_low')}")
    else:
        print("✗ Yahoo Finance 获取失败")

    # 测试 Qveris 备用
    print("\n3. 测试 Qveris 备用数据...")
    qveris_data = fetcher.qveris.get_quote("SLV")
    if qveris_data:
        print(f"✓ Qveris:")
        print(f"  价格: ${qveris_data.get('last_price')}")
        print(f"  涨跌: {qveris_data.get('net_change')}")
    else:
        print("✗ Qveris 获取失败")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)

    return fetcher


if __name__ == "__main__":
    test_fetcher()

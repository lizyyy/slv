#!/usr/bin/env python3
"""
SLV ETF 数据采集模块 V2
数据源优先级：
1. NASDAQ API - 盘前/盘中/盘后实时价格（主要来源）
2. Yahoo Finance - 夜盘/延长时间价格（直接获取）
3. Qveris - 最后备用（当以上都失败时）
"""

import requests
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging
import os
import pytz

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
        self.beijing_tz = pytz.timezone('Asia/Shanghai')
        self.yahoo_error = False

    def is_beijing_night_window(self) -> bool:
        """判断是否在北京时间早上8点到下午16点的夜盘优先窗口"""
        beijing_now = datetime.now(self.beijing_tz)
        hour = beijing_now.hour
        return 8 <= hour < 16

    def get_yahoo_night_session_data(self) -> Tuple[Optional[Dict], bool]:
        """
        直接调用Yahoo API获取夜盘分钟级数据
        返回: (数据字典, 是否成功)
        数据字典包含: is_night_market, last_price, volume, timestamp 等
        """
        yahoo_error = False
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://finance.yahoo.com/',
            }
            url = 'https://query2.finance.yahoo.com/v8/finance/chart/SLV?interval=1m&range=1d&includePrePost=true'
            response = self.session.get(url, headers=headers, timeout=15)
            
            if response.status_code == 429:
                logger.warning("Yahoo API rate limited (429)")
                yahoo_error = True
                return None, True
            if response.status_code != 200:
                logger.warning(f"Yahoo API returned status: {response.status_code}")
                yahoo_error = True
                return None, True
            
            data = response.json()
            result = data.get('chart', {}).get('result', [])
            if not result:
                logger.warning("Yahoo API no result")
                yahoo_error = True
                return None, True
            
            chart_data = result[0]
            meta = chart_data.get('meta', {})
            timestamps = chart_data.get('timestamp', [])
            indicators = chart_data.get('indicators', {}).get('quote', [{}])[0]
            
            if not timestamps or not indicators:
                logger.warning("Yahoo API no timestamps or indicators")
                yahoo_error = True
                return None, True
            
            current_trading_period = meta.get('currentTradingPeriod', {})
            market_state = meta.get('marketState', '').lower()
            
            close_prices = [p for p in indicators.get('close', []) if p is not None]
            volumes = [v for v in indicators.get('volume', []) if v is not None]
            high_prices = [h for h in indicators.get('high', []) if h is not None]
            low_prices = [l for l in indicators.get('low', []) if l is not None]
            
            if not close_prices:
                logger.warning("Yahoo API no close prices")
                yahoo_error = True
                return None, True
            
            is_night_market = False
            if market_state in ['pre', 'post', 'extended']:
                is_night_market = True
            elif self.is_beijing_night_window():
                is_night_market = True
            
            regular_start = None
            regular_end = None
            trading_periods = meta.get('tradingPeriods', [[]])
            if trading_periods and trading_periods[0]:
                for period in trading_periods[0]:
                    if period.get('timezone', '').startswith('America'):
                        regular_start = period.get('start')
                        regular_end = period.get('end')
                        break
            
            if regular_start and regular_end and timestamps:
                last_ts = timestamps[-1]
                if last_ts < regular_start or last_ts >= regular_end:
                    is_night_market = True
            
            previous_close = meta.get('previousClose')
            last_price = close_prices[-1]
            last_timestamp = timestamps[-1] if timestamps else None
            
            result_data = {
                'symbol': 'SLV',
                'last_price': last_price,
                'previous_close': previous_close,
                'timestamp': last_timestamp,
                'is_night_market': is_night_market,
                'data_source': 'yahoo_direct_api',
                'market_status': 'night_session' if is_night_market else 'regular_hours',
                'extended_hours_high': max(high_prices) if high_prices else None,
                'extended_hours_low': min(low_prices) if low_prices else None,
                'volume': int(volumes[-1]) if volumes else None,
                'regular_price': meta.get('regularMarketPrice'),
                'net_change': last_price - previous_close if previous_close and last_price else None,
                'change_pct': ((last_price - previous_close) / previous_close * 100) if previous_close and last_price else None,
            }
            
            return result_data, False
            
        except requests.exceptions.Timeout:
            logger.error("Yahoo API timeout")
            yahoo_error = True
            return None, True
        except requests.exceptions.RequestException as e:
            logger.error(f"Yahoo API request error: {e}")
            yahoo_error = True
            return None, True
        except Exception as e:
            logger.error(f"Yahoo API unexpected error: {e}")
            yahoo_error = True
            return None, True

    def get_yahoo_quote_data(self) -> Tuple[Optional[Dict], bool]:
        """
        调用Yahoo Quote API获取报价信息
        返回: (数据字典, 是否有错误)
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://finance.yahoo.com/',
            }
            url = 'https://query1.finance.yahoo.com/v7/finance/quote?symbols=SLV'
            response = self.session.get(url, headers=headers, timeout=15)
            
            if response.status_code == 429:
                logger.warning("Yahoo Quote API rate limited (429)")
                return None, True
            if response.status_code != 200:
                logger.warning(f"Yahoo Quote API returned status: {response.status_code}")
                return None, True
            
            data = response.json()
            quote = data.get('quoteResponse', {}).get('result', [])
            if not quote:
                logger.warning("Yahoo Quote API no result")
                return None, True
            
            q = quote[0]
            is_night_market = False
            market_state = q.get('marketState', '').lower()
            if market_state in ['pre', 'post', 'extended']:
                is_night_market = True
            elif self.is_beijing_night_window():
                is_night_market = True
            
            result_data = {
                'symbol': q.get('symbol'),
                'last_price': q.get('regularMarketPrice'),
                'net_change': q.get('regularMarketChange'),
                'change_pct': q.get('regularMarketChangePercent'),
                'volume': q.get('regularMarketVolume'),
                'open': q.get('regularMarketOpen'),
                'high': q.get('regularMarketDayHigh'),
                'low': q.get('regularMarketDayLow'),
                'previous_close': q.get('regularMarketPreviousClose'),
                'pre_market_price': q.get('preMarketPrice'),
                'post_market_price': q.get('postMarketPrice'),
                'market_state': market_state,
                'is_night_market': is_night_market,
                'data_source': 'yahoo_quote_api',
            }
            
            return result_data, False
            
        except requests.exceptions.Timeout:
            logger.error("Yahoo Quote API timeout")
            return None, True
        except Exception as e:
            logger.error(f"Yahoo Quote API error: {e}")
            return None, True

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
        【北京时间8:00-16:00夜盘优先模式】:
        1. Yahoo Direct API (夜盘分钟级数据)
        2. Yahoo Quote API
        3. yfinance 库
        4. NASDAQ API
        5. Qveris (最后备用)

        【常规模式】:
        1. NASDAQ API
        2. Yahoo Finance (yfinance)
        3. Qveris (最后备用)
        """
        quote = None
        self.yahoo_error = False
        is_night_window = self.is_beijing_night_window()

        if is_night_window:
            logger.info("北京时间8:00-16:00，启用夜盘优先模式...")

            quote = self._try_yahoo_night_data()
            if not quote:
                self.yahoo_error = True
                logger.warning("Yahoo Direct API 失败，尝试 NASDAQ...")
                quote = self._try_nasdaq_with_yahoo_fallback()
        else:
            logger.info("常规模式，优先尝试 NASDAQ...")
            quote = self._try_nasdaq_with_yahoo_fallback()

        if not quote:
            logger.warning("主要数据源失败，尝试 Qveris 备用...")
            qveris_data = self.qveris.get_quote("SLV")
            if qveris_data and qveris_data.get('last_price'):
                quote = qveris_data
                quote['is_night_market'] = is_night_window
                quote['yahoo_error'] = self.yahoo_error
                logger.info(f"Using Qveris fallback: ${quote['last_price']}")

        if quote:
            if 'is_night_market' not in quote:
                quote['is_night_market'] = is_night_window
            if 'yahoo_error' not in quote:
                quote['yahoo_error'] = self.yahoo_error
            quote['beijing_night_window'] = is_night_window
        else:
            logger.error("所有数据源均失败!")

        return quote

    def _try_yahoo_night_data(self) -> Optional[Dict]:
        """尝试获取 Yahoo 夜盘数据（Direct API + Quote API）"""
        direct_api_error = False
        quote_api_error = False

        logger.info("尝试 Yahoo Direct API 获取夜盘数据...")
        yahoo_data, has_error = self.get_yahoo_night_session_data()
        direct_api_error = has_error
        if yahoo_data:
            logger.info(f"Yahoo Direct API success: ${yahoo_data['last_price']}")
            yahoo_data['yahoo_error'] = False
            return yahoo_data

        logger.info("Yahoo Direct API 失败，尝试 Yahoo Quote API...")
        yahoo_data, has_error = self.get_yahoo_quote_data()
        quote_api_error = has_error
        if yahoo_data:
            logger.info(f"Yahoo Quote API success: ${yahoo_data['last_price']}")
            yahoo_data['yahoo_error'] = False
            return yahoo_data

        self.yahoo_error = True
        logger.info("Yahoo API 均失败，尝试 yfinance 库作为备用...")
        yf_data = self.get_yfinance_data()
        if yf_data and (yf_data.get('regular_price') or yf_data.get('post_market_price') or yf_data.get('pre_market_price')):
            last_price = yf_data.get('post_market_price') or yf_data.get('pre_market_price') or yf_data.get('regular_price')
            result = {
                'symbol': 'SLV',
                'name': 'iShares Silver Trust',
                'last_price': last_price,
                'net_change': None,
                'change_pct': None,
                'volume': None,
                'timestamp': None,
                'is_realtime': False,
                'price_source': 'yfinance_night_fallback',
                'market_status': 'night_session',
                'is_night_market': True,
                'yahoo_error': True,
                'pre_market_price': yf_data.get('pre_market_price'),
                'post_market_price': yf_data.get('post_market_price'),
                'extended_hours_high': yf_data.get('extended_hours_high'),
                'extended_hours_low': yf_data.get('extended_hours_low'),
            }
            logger.info(f"yfinance 夜盘数据获取成功（但 Yahoo API 失败）: ${last_price}")
            return result

        return None

    def _try_nasdaq_with_yahoo_fallback(self) -> Optional[Dict]:
        """尝试 NASDAQ API，失败则用 Yahoo 备用"""
        logger.info("Trying NASDAQ API...")
        quote = self._get_nasdaq_quote()

        if quote:
            logger.info(f"NASDAQ success: ${quote['last_price']}")
            is_night = self.is_beijing_night_window()
            quote['is_night_market'] = is_night or (quote.get('market_status') == 'extended_hours')

            yf_data = self.get_yfinance_data()
            if yf_data:
                quote['pre_market_price'] = yf_data.get('pre_market_price')
                quote['post_market_price'] = yf_data.get('post_market_price')
                quote['extended_hours_high'] = yf_data.get('extended_hours_high')
                quote['extended_hours_low'] = yf_data.get('extended_hours_low')
                quote['yfinance_regular_price'] = yf_data.get('regular_price')

                if yf_data.get('is_extended_hours'):
                    if yf_data.get('pre_market_price') or yf_data.get('post_market_price'):
                        latest_yf = yf_data.get('pre_market_price') or yf_data.get('post_market_price')
                        if latest_yf and quote.get('volume', 0) == 0:
                            logger.info(f"Market in extended hours, using Yahoo price: ${latest_yf}")
                            quote['last_price'] = latest_yf
                            quote['market_status'] = 'extended_hours'
                            quote['price_source'] = 'yfinance_extended_hours'
                            quote['is_night_market'] = True
        else:
            logger.warning("NASDAQ API failed, trying Yahoo Finance...")
            yf_data = self.get_yfinance_data()
            if yf_data and yf_data.get('regular_price'):
                is_night = self.is_beijing_night_window() or yf_data.get('is_extended_hours', False)
                quote = {
                    'symbol': 'SLV',
                    'name': 'iShares Silver Trust',
                    'last_price': yf_data.get('regular_price'),
                    'net_change': None,
                    'change_pct': None,
                    'volume': None,
                    'bid': None,
                    'ask': None,
                    'timestamp': None,
                    'is_realtime': False,
                    'price_source': 'yfinance',
                    'market_status': 'extended_hours' if yf_data.get('is_extended_hours') else 'regular_hours',
                    'is_night_market': is_night,
                    'yahoo_error': False,
                    'pre_market_price': yf_data.get('pre_market_price'),
                    'post_market_price': yf_data.get('post_market_price'),
                    'extended_hours_high': yf_data.get('extended_hours_high'),
                    'extended_hours_low': yf_data.get('extended_hours_low'),
                }
                logger.info(f"Using Yahoo Finance: ${quote['last_price']}")

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

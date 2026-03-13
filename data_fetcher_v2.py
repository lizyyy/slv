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
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def is_beijing_night_session() -> bool:
    """
    判断当前是否在北京时间夜盘时段 (8:00-16:00)
    夜盘时段优先使用雅虎实时数据
    """
    try:
        beijing_tz = timezone(timedelta(hours=8))
        now = datetime.now(beijing_tz)
        hour = now.hour
        return 8 <= hour < 16
    except Exception as e:
        logger.warning(f"判断北京时间时段失败: {e}")
        return False


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
        self.yahoo_timeout_count = 0
        self.yahoo_max_timeout = 3
        self.yahoo_crumb = None
        self.yahoo_cookie = None

    def _get_yahoo_crumb(self) -> Tuple[Optional[str], Optional[str]]:
        """
        获取雅虎API所需的crumb token和cookie
        雅虎API需要这些来验证请求
        """
        if self.yahoo_crumb and self.yahoo_cookie:
            return self.yahoo_crumb, self.yahoo_cookie

        try:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            })

            response = session.get('https://finance.yahoo.com', timeout=10)
            cookies = session.cookies.get_dict()
            cookie_str = '; '.join([f'{k}={v}' for k, v in cookies.items()])

            crumb_response = session.get('https://query1.finance.yahoo.com/v1/test/getcrumb', timeout=10)
            if crumb_response.status_code == 200:
                crumb = crumb_response.text.strip()
                self.yahoo_crumb = crumb
                self.yahoo_cookie = cookie_str
                logger.info(f"获取雅虎crumb成功")
                return crumb, cookie_str

        except Exception as e:
            logger.warning(f"获取雅虎crumb失败: {e}")

        return None, None

    def get_yahoo_realtime_quote(self) -> Optional[Dict]:
        """
        直接调用雅虎API获取实时报价
        接口: https://query1.finance.yahoo.com/v7/finance/quote?symbols=SLV
        """
        if self.yahoo_timeout_count >= self.yahoo_max_timeout:
            logger.warning(f"雅虎API超时次数已达上限({self.yahoo_max_timeout})，跳过本次请求")
            return None

        crumb, cookie = self._get_yahoo_crumb()
        
        url = "https://query1.finance.yahoo.com/v7/finance/quote"
        params = {"symbols": "SLV"}
        if crumb:
            params["crumb"] = crumb
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://finance.yahoo.com',
            'Referer': 'https://finance.yahoo.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
        }
        if cookie:
            headers['Cookie'] = cookie

        try:
            logger.info("Fetching Yahoo Finance realtime quote...")
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            quote_response = data.get('quoteResponse', {})
            results = quote_response.get('result', [])

            if not results:
                logger.warning("Yahoo quote response is empty")
                return None

            quote_data = results[0]
            return {
                'symbol': 'SLV',
                'name': quote_data.get('longName', 'iShares Silver Trust'),
                'last_price': quote_data.get('regularMarketPrice'),
                'net_change': quote_data.get('regularMarketChange'),
                'change_pct': quote_data.get('regularMarketChangePercent'),
                'volume': quote_data.get('regularMarketVolume'),
                'open': quote_data.get('regularMarketOpen'),
                'high': quote_data.get('regularMarketDayHigh'),
                'low': quote_data.get('regularMarketDayLow'),
                'previous_close': quote_data.get('regularMarketPreviousClose'),
                'fifty_two_week_high': quote_data.get('fiftyTwoWeekHigh'),
                'fifty_two_week_low': quote_data.get('fiftyTwoWeekLow'),
                'pre_market_price': quote_data.get('preMarketPrice'),
                'post_market_price': quote_data.get('postMarketPrice'),
                'market_state': quote_data.get('marketState'),
                'data_source': 'yahoo_api_direct',
                'yahoo_fetch_failed': False,
                'yahoo_fetch_timeout': False
            }

        except requests.exceptions.Timeout:
            self.yahoo_timeout_count += 1
            logger.error(f"Yahoo API timeout ({self.yahoo_timeout_count}/{self.yahoo_max_timeout})")
            return {
                'symbol': 'SLV',
                'last_price': None,
                'data_source': 'yahoo_api_direct',
                'yahoo_fetch_failed': True,
                'yahoo_fetch_timeout': True
            }
        except Exception as e:
            logger.error(f"Yahoo API error: {e}")
            return {
                'symbol': 'SLV',
                'last_price': None,
                'data_source': 'yahoo_api_direct',
                'yahoo_fetch_failed': True,
                'yahoo_fetch_timeout': False
            }

    def get_yahoo_minute_chart(self) -> Optional[Dict]:
        """
        直接调用雅虎API获取分钟级行情/夜盘数据
        接口: https://query2.finance.yahoo.com/v8/finance/chart/SLV?interval=1m&range=1d&includePrePost=true
        """
        if self.yahoo_timeout_count >= self.yahoo_max_timeout:
            logger.warning(f"雅虎API超时次数已达上限({self.yahoo_max_timeout})，跳过本次请求")
            return None

        crumb, cookie = self._get_yahoo_crumb()

        url = "https://query2.finance.yahoo.com/v8/finance/chart/SLV"
        params = {
            "interval": "1m",
            "range": "1d",
            "includePrePost": "true"
        }
        if crumb:
            params["crumb"] = crumb
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://finance.yahoo.com',
            'Referer': 'https://finance.yahoo.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
        }
        if cookie:
            headers['Cookie'] = cookie

        try:
            logger.info("Fetching Yahoo Finance minute chart (night session data)...")
            response = requests.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()

            chart_result = data.get('chart', {}).get('result', [])
            if not chart_result:
                logger.warning("Yahoo chart response is empty")
                return None

            result = chart_result[0]
            meta = result.get('meta', {})
            timestamps = result.get('timestamp', [])
            indicators = result.get('indicators', {}).get('quote', [])

            if not timestamps or not indicators:
                logger.warning("Yahoo chart data incomplete")
                return None

            quote_data = indicators[0]
            minute_prices = []
            for i, ts in enumerate(timestamps):
                if ts and quote_data.get('close') and i < len(quote_data['close']):
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    minute_prices.append({
                        'datetime': dt,
                        'timestamp': ts,
                        'open': quote_data['open'][i] if quote_data.get('open') else None,
                        'high': quote_data['high'][i] if quote_data.get('high') else None,
                        'low': quote_data['low'][i] if quote_data.get('low') else None,
                        'close': quote_data['close'][i] if quote_data.get('close') else None,
                        'volume': quote_data['volume'][i] if quote_data.get('volume') else None
                    })

            latest_price = meta.get('regularMarketPrice')
            if minute_prices:
                latest_price = minute_prices[-1]['close'] or latest_price

            return {
                'symbol': 'SLV',
                'name': meta.get('shortName', 'iShares Silver Trust'),
                'last_price': latest_price,
                'previous_close': meta.get('chartPreviousClose'),
                'regular_market_price': meta.get('regularMarketPrice'),
                'fifty_two_week_high': meta.get('fiftyTwoWeekHigh'),
                'fifty_two_week_low': meta.get('fiftyTwoWeekLow'),
                'day_high': meta.get('regularMarketDayHigh'),
                'day_low': meta.get('regularMarketDayLow'),
                'volume': meta.get('regularMarketVolume'),
                'currency': meta.get('currency', 'USD'),
                'exchange': meta.get('exchangeName'),
                'minute_prices': minute_prices,
                'data_source': 'yahoo_chart_api',
                'yahoo_fetch_failed': False,
                'yahoo_fetch_timeout': False
            }

        except requests.exceptions.Timeout:
            self.yahoo_timeout_count += 1
            logger.error(f"Yahoo Chart API timeout ({self.yahoo_timeout_count}/{self.yahoo_max_timeout})")
            return {
                'symbol': 'SLV',
                'last_price': None,
                'data_source': 'yahoo_chart_api',
                'yahoo_fetch_failed': True,
                'yahoo_fetch_timeout': True
            }
        except Exception as e:
            logger.error(f"Yahoo Chart API error: {e}")
            return {
                'symbol': 'SLV',
                'last_price': None,
                'data_source': 'yahoo_chart_api',
                'yahoo_fetch_failed': True,
                'yahoo_fetch_timeout': False
            }

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
        - 北京时间 8:00-16:00 (夜盘时段):
          1. Yahoo Finance API (直接调用) - 优先获取夜盘数据
          2. NASDAQ API - 备用
          3. Qveris - 最后备用
        - 其他时段:
          1. NASDAQ API（盘前/盘中/盘后实时价格）- 主要来源
          2. Yahoo Finance（夜盘价格）- 补充延长时间数据
          3. Qveris（最后备用）
        """
        quote = None
        is_night_session = is_beijing_night_session()

        if is_night_session:
            logger.info("检测到北京时间夜盘时段 (8:00-16:00)，优先使用雅虎API...")

            yahoo_quote = self.get_yahoo_realtime_quote()
            yahoo_chart = self.get_yahoo_minute_chart()

            if yahoo_quote and yahoo_quote.get('last_price') and not yahoo_quote.get('yahoo_fetch_failed'):
                quote = yahoo_quote.copy()
                quote['is_night_session'] = True
                quote['market_status'] = 'night_session'
                quote['price_source'] = 'yahoo_api_night_session'
                quote['yahoo_fetch_failed'] = False
                quote['yahoo_fetch_timeout'] = False

                if yahoo_chart and yahoo_chart.get('minute_prices'):
                    quote['minute_prices'] = yahoo_chart['minute_prices']
                    quote['day_high'] = yahoo_chart.get('day_high')
                    quote['day_low'] = yahoo_chart.get('day_low')

                logger.info(f"Yahoo API 夜盘数据获取成功: ${quote['last_price']}")
            else:
                yahoo_failed = yahoo_quote.get('yahoo_fetch_failed') if yahoo_quote else True
                yahoo_timeout = yahoo_quote.get('yahoo_fetch_timeout') if yahoo_quote else False

                logger.warning(f"Yahoo API 夜盘数据获取失败，尝试备用数据源...")

                nasdaq_quote = self._get_nasdaq_quote()
                if nasdaq_quote and nasdaq_quote.get('last_price'):
                    quote = nasdaq_quote
                    quote['is_night_session'] = True
                    quote['yahoo_fetch_failed'] = yahoo_failed
                    quote['yahoo_fetch_timeout'] = yahoo_timeout
                    logger.info(f"使用 NASDAQ 备用数据: ${quote['last_price']}")
                else:
                    qveris_quote = self.qveris.get_quote("SLV")
                    if qveris_quote and qveris_quote.get('last_price'):
                        quote = qveris_quote
                        quote['is_night_session'] = True
                        quote['yahoo_fetch_failed'] = yahoo_failed
                        quote['yahoo_fetch_timeout'] = yahoo_timeout
                        logger.info(f"使用 Qveris 备用数据: ${quote['last_price']}")
        else:
            logger.info("非夜盘时段，使用常规数据源优先级...")

            logger.info("Trying NASDAQ API...")
            quote = self._get_nasdaq_quote()

            if quote:
                logger.info(f"NASDAQ success: ${quote['last_price']}")

                logger.info("Fetching Yahoo Finance extended hours data...")
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

                    logger.info(f"Yahoo Finance extended hours: pre=${yf_data.get('pre_market_price')}, post=${yf_data.get('post_market_price')}")

                quote['is_night_session'] = False
                quote['yahoo_fetch_failed'] = False
                quote['yahoo_fetch_timeout'] = False
            else:
                logger.warning("NASDAQ API failed, trying Yahoo Finance...")

                yf_data = self.get_yfinance_data()
                if yf_data and yf_data.get('regular_price'):
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
                        'pre_market_price': yf_data.get('pre_market_price'),
                        'post_market_price': yf_data.get('post_market_price'),
                        'extended_hours_high': yf_data.get('extended_hours_high'),
                        'extended_hours_low': yf_data.get('extended_hours_low'),
                        'is_night_session': False,
                        'yahoo_fetch_failed': False,
                        'yahoo_fetch_timeout': False,
                    }
                    logger.info(f"Using Yahoo Finance: ${quote['last_price']}")

        if not quote:
            logger.warning("All primary sources failed, trying Qveris as fallback...")
            qveris_data = self.qveris.get_quote("SLV")
            if qveris_data and qveris_data.get('last_price'):
                quote = qveris_data
                quote['is_night_session'] = is_night_session
                quote['yahoo_fetch_failed'] = True
                quote['yahoo_fetch_timeout'] = False
                logger.info(f"Using Qveris fallback: ${quote['last_price']}")

        if not quote:
            logger.error("All data sources failed!")
            return {
                'symbol': 'SLV',
                'last_price': None,
                'is_night_session': is_night_session,
                'yahoo_fetch_failed': True,
                'yahoo_fetch_timeout': False,
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
    fetcher = SLVDataFetcher(data_dir="/Users/lzy/pro/dogfood/pro_18/br_02")

    print("=" * 60)
    print("测试SLV数据采集器 V2 (支持夜盘时段)")
    print("=" * 60)

    print(f"\n当前北京时间时段: {'夜盘时段 (8:00-16:00)' if is_beijing_night_session() else '非夜盘时段'}")

    print("\n1. 获取实时报价...")
    quote = fetcher.get_current_quote()
    if quote:
        print(f"✓ 实时报价:")
        print(f"  当前价: ${quote.get('last_price', 'N/A')}")
        print(f"  涨跌: {quote.get('net_change', 'N/A')}")
        print(f"  涨跌幅: {quote.get('change_pct', 'N/A')}%")
        print(f"  成交量: {quote.get('volume', 'N/A')}")
        print(f"  数据源: {quote.get('price_source', quote.get('data_source', 'N/A'))}")
        print(f"  市场状态: {quote.get('market_status', 'N/A')}")
        print(f"  --- 夜盘标记 ---")
        print(f"  是否夜盘价格: {'是' if quote.get('is_night_session') else '否'}")
        print(f"  雅虎获取失败: {'是' if quote.get('yahoo_fetch_failed') else '否'}")
        print(f"  雅虎超时: {'是' if quote.get('yahoo_fetch_timeout') else '否'}")
        if quote.get('pre_market_price'):
            print(f"  盘前价: ${quote['pre_market_price']}")
        if quote.get('post_market_price'):
            print(f"  盘后价: ${quote['post_market_price']}")
        if quote.get('day_high'):
            print(f"  日最高: ${quote['day_high']}")
        if quote.get('day_low'):
            print(f"  日最低: ${quote['day_low']}")
        if quote.get('minute_prices'):
            print(f"  分钟数据条数: {len(quote['minute_prices'])}")
    else:
        print("✗ 获取实时报价失败")

    print("\n2. 测试雅虎API直接获取报价...")
    yahoo_quote = fetcher.get_yahoo_realtime_quote()
    if yahoo_quote and not yahoo_quote.get('yahoo_fetch_failed'):
        print(f"✓ 雅虎报价API:")
        print(f"  价格: ${yahoo_quote.get('last_price')}")
        print(f"  盘前价: ${yahoo_quote.get('pre_market_price')}")
        print(f"  盘后价: ${yahoo_quote.get('post_market_price')}")
        print(f"  市场状态: {yahoo_quote.get('market_state')}")
    else:
        print(f"✗ 雅虎报价API获取失败 (timeout={yahoo_quote.get('yahoo_fetch_timeout') if yahoo_quote else 'N/A'})")

    print("\n3. 测试雅虎分钟级行情...")
    yahoo_chart = fetcher.get_yahoo_minute_chart()
    if yahoo_chart and not yahoo_chart.get('yahoo_fetch_failed'):
        print(f"✓ 雅虎分钟行情API:")
        print(f"  最新价: ${yahoo_chart.get('last_price')}")
        print(f"  昨收: ${yahoo_chart.get('previous_close')}")
        print(f"  分钟数据条数: {len(yahoo_chart.get('minute_prices', []))}")
    else:
        print(f"✗ 雅虎分钟行情API获取失败 (timeout={yahoo_chart.get('yahoo_fetch_timeout') if yahoo_chart else 'N/A'})")

    print("\n4. 测试 Qveris 备用数据...")
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

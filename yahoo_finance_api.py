#!/usr/bin/env python3
"""
Yahoo Finance API 直接获取模块
用于获取SLV夜盘/延长时间价格数据

接口说明：
- 分钟级行情/夜盘数据: https://query2.finance.yahoo.com/v8/finance/chart/SLV?interval=1m&range=1d&includePrePost=true
- 报价信息接口: https://query1.finance.yahoo.com/v7/finance/quote?symbols=SLV
"""

import requests
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PriceType(Enum):
    """价格类型"""
    REGULAR_HOURS = "regular_hours"      # 常规交易时间
    PRE_MARKET = "pre_market"            # 盘前
    POST_MARKET = "post_market"          # 盘后
    EXTENDED_HOURS = "extended_hours"    # 延长时间（盘前或盘后）
    UNKNOWN = "unknown"                  # 未知


class DataSourceStatus(Enum):
    """数据源状态"""
    SUCCESS = "success"                  # 成功
    TIMEOUT = "timeout"                  # 超时
    RATE_LIMITED = "rate_limited"        # 频次受限
    ERROR = "error"                      # 错误
    UNAVAILABLE = "unavailable"          # 不可用


@dataclass
class YahooPriceData:
    """雅虎价格数据结构"""
    symbol: str
    last_price: Optional[float]
    previous_close: Optional[float]
    net_change: Optional[float]
    change_pct: Optional[float]
    volume: Optional[int]
    price_type: PriceType
    is_extended_hours: bool
    data_source: str
    source_status: DataSourceStatus
    
    # 延长时间数据
    pre_market_price: Optional[float] = None
    post_market_price: Optional[float] = None
    extended_hours_high: Optional[float] = None
    extended_hours_low: Optional[float] = None
    
    # 时间信息
    timestamp: Optional[datetime] = None
    market_time: Optional[datetime] = None
    
    # 错误信息
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'last_price': self.last_price,
            'previous_close': self.previous_close,
            'net_change': self.net_change,
            'change_pct': self.change_pct,
            'volume': self.volume,
            'price_type': self.price_type.value,
            'is_extended_hours': self.is_extended_hours,
            'data_source': self.data_source,
            'source_status': self.source_status.value,
            'pre_market_price': self.pre_market_price,
            'post_market_price': self.post_market_price,
            'extended_hours_high': self.extended_hours_high,
            'extended_hours_low': self.extended_hours_low,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'market_time': self.market_time.isoformat() if self.market_time else None,
            'error_message': self.error_message
        }


class YahooFinanceAPI:
    """Yahoo Finance API 客户端"""
    
    # API 端点
    CHART_API_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    QUOTE_API_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
    
    # 请求头 - 需要包含Cookie以通过Yahoo的验证
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Origin': 'https://finance.yahoo.com',
        'Referer': 'https://finance.yahoo.com/',
        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"macOS"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
    }
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
    
    def get_chart_data(self, symbol: str = "SLV", interval: str = "1m", 
                       range_period: str = "1d", include_prepost: bool = True) -> Optional[Dict]:
        """
        获取图表数据（包含夜盘数据）
        
        Args:
            symbol: 股票代码
            interval: 时间间隔 (1m, 2m, 5m, 15m, 30m, 60m, 1d, 1wk, 1mo)
            range_period: 时间范围 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            include_prepost: 是否包含盘前盘后数据
        """
        url = self.CHART_API_URL.format(symbol=symbol)
        params = {
            'interval': interval,
            'range': range_period,
            'includePrePost': 'true' if include_prepost else 'false'
        }
        
        try:
            logger.info(f"Fetching Yahoo chart data for {symbol}...")
            response = self.session.get(url, params=params, timeout=self.timeout)
            
            if response.status_code == 429:
                logger.warning("Yahoo API rate limited (429)")
                return {'error': 'rate_limited', 'status_code': 429}
            
            if response.status_code == 404:
                logger.warning(f"Yahoo API returned 404 for {symbol}")
                return {'error': 'not_found', 'status_code': 404}
            
            response.raise_for_status()
            data = response.json()
            
            if data.get('chart', {}).get('error'):
                error_info = data['chart']['error']
                logger.warning(f"Yahoo API error: {error_info}")
                return {'error': 'api_error', 'details': error_info}
            
            return data
            
        except requests.exceptions.Timeout:
            logger.error(f"Yahoo API timeout after {self.timeout}s")
            return {'error': 'timeout'}
        except requests.exceptions.RequestException as e:
            logger.error(f"Yahoo API request error: {e}")
            return {'error': 'request_error', 'details': str(e)}
        except json.JSONDecodeError as e:
            logger.error(f"Yahoo API JSON decode error: {e}")
            return {'error': 'json_decode_error'}
    
    def get_quote_data(self, symbols: List[str] = None) -> Optional[Dict]:
        """
        获取报价信息
        
        Args:
            symbols: 股票代码列表，默认 ["SLV"]
        """
        if symbols is None:
            symbols = ["SLV"]
        
        params = {
            'symbols': ','.join(symbols)
        }
        
        try:
            logger.info(f"Fetching Yahoo quote data for {symbols}...")
            response = self.session.get(self.QUOTE_API_URL, params=params, timeout=self.timeout)
            
            if response.status_code == 429:
                logger.warning("Yahoo API rate limited (429)")
                return {'error': 'rate_limited', 'status_code': 429}
            
            response.raise_for_status()
            data = response.json()
            
            if data.get('quoteResponse', {}).get('error'):
                error_info = data['quoteResponse']['error']
                logger.warning(f"Yahoo API error: {error_info}")
                return {'error': 'api_error', 'details': error_info}
            
            return data
            
        except requests.exceptions.Timeout:
            logger.error(f"Yahoo API timeout after {self.timeout}s")
            return {'error': 'timeout'}
        except requests.exceptions.RequestException as e:
            logger.error(f"Yahoo API request error: {e}")
            return {'error': 'request_error', 'details': str(e)}
    
    def parse_chart_data(self, data: Dict) -> YahooPriceData:
        """
        解析图表数据，提取夜盘价格信息
        """
        symbol = "SLV"
        
        if not data or 'chart' not in data:
            return YahooPriceData(
                symbol=symbol,
                last_price=None,
                previous_close=None,
                net_change=None,
                change_pct=None,
                volume=None,
                price_type=PriceType.UNKNOWN,
                is_extended_hours=False,
                data_source='yahoo_chart',
                source_status=DataSourceStatus.ERROR,
                error_message="Invalid chart data"
            )
        
        result = data.get('chart', {}).get('result', [{}])[0]
        meta = result.get('meta', {})
        
        # 获取时间戳和价格数据
        timestamps = result.get('timestamp', [])
        indicators = result.get('indicators', {})
        quote_data = indicators.get('quote', [{}])[0]
        
        # 获取当前交易时段信息
        current_trading_period = meta.get('currentTradingPeriod', {})
        regular_period = current_trading_period.get('regular', {})
        pre_period = current_trading_period.get('pre', {})
        post_period = current_trading_period.get('post', {})
        
        # 获取价格数据
        closes = quote_data.get('close', [])
        highs = quote_data.get('high', [])
        lows = quote_data.get('low', [])
        volumes = quote_data.get('volume', [])
        
        # 获取元数据
        regular_price = meta.get('regularMarketPrice')
        previous_close = meta.get('chartPreviousClose') or meta.get('previousClose')
        
        # 确定当前市场状态和价格
        now = datetime.now()
        current_price = None
        price_type = PriceType.UNKNOWN
        is_extended = False
        
        # 尝试从数据中确定价格
        if closes:
            # 获取最后一个有效价格
            valid_closes = [c for c in closes if c is not None]
            if valid_closes:
                current_price = valid_closes[-1]
        
        # 如果图表数据没有当前价格，使用元数据中的常规市场价格
        if current_price is None and regular_price:
            current_price = regular_price
        
        # 判断是否为延长时间
        # 根据数据粒度判断：如果有盘前或盘后数据点，则为延长时间
        if timestamps and len(timestamps) > 0:
            # 获取最后一个数据点的时间
            last_timestamp = timestamps[-1]
            last_time = datetime.fromtimestamp(last_timestamp)
            
            # 判断市场状态
            regular_start = regular_period.get('start')
            regular_end = regular_period.get('end')
            
            if regular_start and regular_end:
                if last_timestamp < regular_start or last_timestamp > regular_end:
                    is_extended = True
                    if last_timestamp < regular_start:
                        price_type = PriceType.PRE_MARKET
                    else:
                        price_type = PriceType.POST_MARKET
                else:
                    price_type = PriceType.REGULAR_HOURS
        
        # 计算涨跌
        net_change = None
        change_pct = None
        if current_price and previous_close:
            net_change = current_price - previous_close
            change_pct = (net_change / previous_close) * 100
        
        # 计算延长时间高低点
        extended_high = None
        extended_low = None
        if highs and lows:
            valid_highs = [h for h in highs if h is not None]
            valid_lows = [l for l in lows if l is not None]
            if valid_highs:
                extended_high = max(valid_highs)
            if valid_lows:
                extended_low = min(valid_lows)
        
        # 获取成交量
        volume = None
        if volumes:
            valid_volumes = [v for v in volumes if v is not None]
            if valid_volumes:
                volume = int(valid_volumes[-1])
        
        return YahooPriceData(
            symbol=symbol,
            last_price=current_price,
            previous_close=previous_close,
            net_change=net_change,
            change_pct=change_pct,
            volume=volume,
            price_type=price_type,
            is_extended_hours=is_extended,
            data_source='yahoo_chart',
            source_status=DataSourceStatus.SUCCESS,
            extended_hours_high=extended_high,
            extended_hours_low=extended_low,
            timestamp=now,
            market_time=datetime.fromtimestamp(timestamps[-1]) if timestamps else None
        )
    
    def parse_quote_data(self, data: Dict) -> YahooPriceData:
        """
        解析报价数据
        """
        symbol = "SLV"
        
        if not data or 'quoteResponse' not in data:
            return YahooPriceData(
                symbol=symbol,
                last_price=None,
                previous_close=None,
                net_change=None,
                change_pct=None,
                volume=None,
                price_type=PriceType.UNKNOWN,
                is_extended_hours=False,
                data_source='yahoo_quote',
                source_status=DataSourceStatus.ERROR,
                error_message="Invalid quote data"
            )
        
        quotes = data.get('quoteResponse', {}).get('result', [])
        if not quotes:
            return YahooPriceData(
                symbol=symbol,
                last_price=None,
                previous_close=None,
                net_change=None,
                change_pct=None,
                volume=None,
                price_type=PriceType.UNKNOWN,
                is_extended_hours=False,
                data_source='yahoo_quote',
                source_status=DataSourceStatus.ERROR,
                error_message="No quote results"
            )
        
        quote = quotes[0]
        
        # 获取价格信息
        regular_price = quote.get('regularMarketPrice')
        pre_price = quote.get('preMarketPrice')
        post_price = quote.get('postMarketPrice')
        previous_close = quote.get('regularMarketPreviousClose')
        
        # 确定使用哪个价格
        current_price = None
        price_type = PriceType.REGULAR_HOURS
        is_extended = False
        
        # 优先使用盘后价格（如果存在且更新）
        if post_price and quote.get('postMarketTime', 0) > quote.get('regularMarketTime', 0):
            current_price = post_price
            price_type = PriceType.POST_MARKET
            is_extended = True
        # 其次使用盘前价格
        elif pre_price:
            current_price = pre_price
            price_type = PriceType.PRE_MARKET
            is_extended = True
        # 最后使用常规价格
        elif regular_price:
            current_price = regular_price
            price_type = PriceType.REGULAR_HOURS
        
        # 计算涨跌
        net_change = quote.get('regularMarketChange')
        change_pct = quote.get('regularMarketChangePercent')
        
        # 如果当前是延长时间，计算基于前收盘的涨跌
        if is_extended and current_price and previous_close:
            if net_change is None:
                net_change = current_price - previous_close
            if change_pct is None:
                change_pct = (net_change / previous_close) * 100
        
        return YahooPriceData(
            symbol=symbol,
            last_price=current_price,
            previous_close=previous_close,
            net_change=net_change,
            change_pct=change_pct,
            volume=quote.get('regularMarketVolume'),
            price_type=price_type,
            is_extended_hours=is_extended,
            data_source='yahoo_quote',
            source_status=DataSourceStatus.SUCCESS,
            pre_market_price=pre_price,
            post_market_price=post_price,
            timestamp=datetime.now(),
            market_time=datetime.fromtimestamp(quote.get('regularMarketTime', 0)) if quote.get('regularMarketTime') else None
        )
    
    def get_extended_hours_price(self, symbol: str = "SLV") -> YahooPriceData:
        """
        获取延长时间价格（夜盘价格）
        优先使用图表API获取详细的夜盘数据
        """
        # 首先尝试图表API（包含详细的分钟级夜盘数据）
        chart_data = self.get_chart_data(symbol=symbol, interval="1m", range_period="1d", include_prepost=True)
        
        if chart_data and 'error' not in chart_data:
            logger.info("Successfully fetched extended hours data from Yahoo chart API")
            return self.parse_chart_data(chart_data)
        
        # 如果图表API失败，尝试报价API
        logger.warning("Chart API failed, trying quote API...")
        quote_data = self.get_quote_data([symbol])
        
        if quote_data and 'error' not in quote_data:
            logger.info("Successfully fetched data from Yahoo quote API")
            return self.parse_quote_data(quote_data)
        
        # 两个API都失败
        error_msg = "Both Yahoo APIs failed"
        if chart_data and 'error' in chart_data:
            error_msg += f" (chart: {chart_data.get('error')})"
        if quote_data and 'error' in quote_data:
            error_msg += f" (quote: {quote_data.get('error')})"
        
        logger.error(error_msg)
        
        # 确定错误状态
        status = DataSourceStatus.ERROR
        if chart_data:
            if chart_data.get('error') == 'timeout':
                status = DataSourceStatus.TIMEOUT
            elif chart_data.get('error') == 'rate_limited' or chart_data.get('status_code') == 429:
                status = DataSourceStatus.RATE_LIMITED
        
        return YahooPriceData(
            symbol=symbol,
            last_price=None,
            previous_close=None,
            net_change=None,
            change_pct=None,
            volume=None,
            price_type=PriceType.UNKNOWN,
            is_extended_hours=False,
            data_source='yahoo',
            source_status=status,
            error_message=error_msg,
            timestamp=datetime.now()
        )


def is_beijing_extended_hours() -> bool:
    """
    判断当前是否为北京时间延长时间（早上8点到下午16点）
    这个时间段对应美东时间的晚上/夜间，可以获取夜盘数据
    
    北京时间 8:00-16:00 = 美东时间 19:00-03:00 (夏令时) 或 20:00-04:00 (冬令时)
    这个时间段美股处于盘后或盘前交易时间
    """
    # 获取当前北京时间
    from datetime import timezone
    utc_now = datetime.now(timezone.utc)
    beijing_offset = timedelta(hours=8)
    beijing_now = utc_now + beijing_offset
    
    hour = beijing_now.hour
    
    # 北京时间 8:00 - 16:00
    return 8 <= hour < 16


def get_slv_price_with_fallback(use_yahoo_priority: bool = False) -> Dict:
    """
    获取SLV价格，支持优先级控制和错误处理
    
    Args:
        use_yahoo_priority: 是否优先使用雅虎数据（用于北京时间延长时间）
    
    Returns:
        包含价格信息和数据源状态的字典
    """
    yahoo_api = YahooFinanceAPI()
    
    # 如果优先使用雅虎数据（北京时间延长时间）
    if use_yahoo_priority:
        logger.info("Using Yahoo Finance as priority data source (Beijing extended hours)")
        yahoo_data = yahoo_api.get_extended_hours_price("SLV")
        
        # 如果雅虎数据成功获取
        if yahoo_data.source_status == DataSourceStatus.SUCCESS and yahoo_data.last_price:
            result = yahoo_data.to_dict()
            result['is_fallback'] = False
            result['priority_source'] = 'yahoo'
            return result
        
        # 雅虎失败，标记为fallback
        logger.warning(f"Yahoo data failed: {yahoo_data.source_status.value}, will use fallback")
        result = yahoo_data.to_dict()
        result['is_fallback'] = True
        result['priority_source'] = 'yahoo'
        result['fallback_reason'] = yahoo_data.source_status.value
        return result
    
    # 常规流程：先尝试其他数据源，雅虎作为备选
    else:
        yahoo_data = yahoo_api.get_extended_hours_price("SLV")
        result = yahoo_data.to_dict()
        result['is_fallback'] = False
        result['priority_source'] = 'other'
        return result


# 便捷函数
def get_yahoo_slv_data() -> Dict:
    """
    获取雅虎SLV数据的便捷函数
    自动判断是否需要优先使用雅虎数据
    """
    is_extended_hours_time = is_beijing_extended_hours()
    return get_slv_price_with_fallback(use_yahoo_priority=is_extended_hours_time)


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("Yahoo Finance API 测试")
    print("=" * 60)
    
    # 测试时间判断
    print(f"\n当前是否为北京时间延长时间 (8:00-16:00): {is_beijing_extended_hours()}")
    
    # 测试获取数据
    print("\n测试获取SLV数据...")
    data = get_yahoo_slv_data()
    
    print(f"\n数据源: {data['data_source']}")
    print(f"状态: {data['source_status']}")
    print(f"当前价格: ${data['last_price']}")
    print(f"前收盘: ${data['previous_close']}")
    
    net_change = data['net_change']
    change_pct = data['change_pct']
    if net_change is not None and change_pct is not None:
        print(f"涨跌: {net_change:+.2f} ({change_pct:+.2f}%)")
    else:
        print(f"涨跌: N/A")
    
    print(f"成交量: {data['volume']}")
    print(f"价格类型: {data['price_type']}")
    print(f"是否夜盘: {data['is_extended_hours']}")
    print(f"盘前价: ${data['pre_market_price']}")
    print(f"盘后价: ${data['post_market_price']}")
    print(f"夜盘最高: ${data['extended_hours_high']}")
    print(f"夜盘最低: ${data['extended_hours_low']}")
    print(f"是否fallback: {data.get('is_fallback', False)}")
    print(f"优先级数据源: {data.get('priority_source', 'N/A')}")
    
    if data.get('error_message'):
        print(f"错误信息: {data['error_message']}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

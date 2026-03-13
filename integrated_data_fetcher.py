#!/usr/bin/env python3
"""
整合数据采集模块
结合NASDAQ实时数据、本地历史数据和Yahoo市场数据
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# 导入现有模块
from data_fetcher_v2 import SLVDataFetcher
from market_data_fetcher import MarketDataFetcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class IntegratedDataFetcher:
    """整合数据获取器 - 统一入口"""

    def __init__(self, data_dir: str = "/Users/lzy/go/pro/slv"):
        self.data_dir = Path(data_dir)
        self.nasdaq_fetcher = SLVDataFetcher(data_dir=data_dir)
        self.market_fetcher = MarketDataFetcher()

    def get_complete_data(self) -> Dict:
        """
        获取完整的分析数据
        包括NASDAQ数据、历史数据和市场关联数据
        """
        logger.info("=" * 60)
        logger.info("开始获取完整数据集...")
        logger.info("=" * 60)

        # 1. 获取NASDAQ实时和历史数据
        nasdaq_data = self.nasdaq_fetcher.get_analysis_data()

        # 2. 获取市场关联数据
        market_data = self.market_fetcher.get_all_market_data()

        # 3. 获取资金流向估算
        fund_flows = self.market_fetcher.get_slv_fund_flows()

        # 4. 整合数据
        complete_data = {
            "timestamp": datetime.now().isoformat(),
            "symbol": "SLV",
            "nasdaq_data": nasdaq_data,
            "market_data": market_data,
            "fund_flows": fund_flows
        }

        logger.info("=" * 60)
        logger.info("数据获取完成")
        logger.info("=" * 60)

        return complete_data

    def get_data_for_sentiment_analysis(self) -> Dict:
        """
        获取市场情绪分析所需的数据（完整版）
        """
        complete_data = self.get_complete_data()
        nasdaq_data = complete_data['nasdaq_data']
        market_data = complete_data['market_data']
        fund_flows = complete_data['fund_flows']

        hist = nasdaq_data.get("historical_daily", [])
        quote = nasdaq_data.get("current_quote", {})

        if not hist:
            return {}

        latest = hist[-1]
        prev = hist[-2] if len(hist) > 1 else latest

        # 优先使用实时报价数据
        current_price = quote.get('last_price') or latest.get('close', 0)
        current_volume = quote.get('volume') if quote.get('volume') is not None else latest.get('volume', 0)
        net_change = quote.get('net_change', 0)
        change_pct = quote.get('change_pct', 0)

        prev_close = prev.get('close', current_price)

        # 如果实时报价没有涨跌数据，则从历史数据计算
        if not net_change and current_price and prev_close:
            net_change = current_price - prev_close
            change_pct = (net_change / prev_close * 100) if prev_close else 0

        # 计算52周位置
        closes = [h.get('close') for h in hist if h.get('close')]
        high_52w = max(closes) if closes else current_price
        low_52w = min(closes) if closes else current_price
        price_position = ((current_price - low_52w) / (high_52w - low_52w)) if (high_52w - low_52w) > 0 else 0.5

        # 成交量
        volumes = [h.get('volume', 0) for h in hist[-20:] if h.get('volume')]
        avg_volume = sum(volumes) / len(volumes) if volumes else 1

        # 关联市场数据（防御性处理None值）
        dxy_data = market_data.get('dxy') or {}
        vix_data = market_data.get('vix') or {}
        gold_data = market_data.get('gold_futures') or {}
        yield_data = market_data.get('ten_year_yield') or {}
        gsr_data = market_data.get('gold_silver_ratio') or {}
        fear_greed = market_data.get('fear_greed') or {}

        return {
            "price_data": {
                "current_price": round(current_price, 2) if current_price else None,
                "price_change_1d": round(net_change, 2),
                "price_change_pct": round(change_pct, 2),
                "volume": current_volume,
                "volume_vs_avg": round(current_volume / avg_volume, 2) if avg_volume else 1.0,
                "high_52w": round(high_52w, 2),
                "low_52w": round(low_52w, 2),
                "price_position": round(price_position, 2),
                "quote_source": quote.get("price_source"),
                "market_status": quote.get("market_status"),
                "is_night_session_price": quote.get("is_night_session", False),
                "yahoo_preferred_window": quote.get("yahoo_preferred_window", False),
                "yahoo_attempted": quote.get("yahoo_attempted", False),
                "yahoo_available": quote.get("yahoo_available", False),
                "yahoo_used_for_price": quote.get("yahoo_used_for_price", False),
                "yahoo_failure_reason": quote.get("yahoo_failure_reason"),
                "yahoo_failure_message": quote.get("yahoo_failure_message"),
                "yahoo_rate_limited": quote.get("yahoo_rate_limited", False),
                "yahoo_timed_out": quote.get("yahoo_timed_out", False),
                "yahoo_status": quote.get("yahoo_status"),
            },
            "correlated_markets": {
                "dxy": {
                    "value": dxy_data.get('value'),
                    "change_pct": dxy_data.get('change_pct')
                },
                "vix": {
                    "value": vix_data.get('value'),
                    "change_pct": vix_data.get('change_pct')
                },
                "gold_futures": {
                    "price": gold_data.get('gold_spot_estimate'),
                    "change_pct": gold_data.get('change_pct')
                },
                "ten_year_yield": {
                    "value": yield_data.get('value'),
                    "change_pct": yield_data.get('change_pct')
                }
            },
            "gold_silver_ratio": gsr_data if gsr_data else {
                "current": None,
                "historical_mean": 65.0,
                "historical_range": [50, 85],
                "percentile": None
            },
            "fear_greed": fear_greed if fear_greed else {
                "index_value": None,
                "category": None,
                "previous_day": None,
                "trend": None
            },
            "fund_flows": fund_flows if fund_flows else {
                "etf_inflow_1d": None,
                "etf_inflow_5d": None,
                "institutional_holdings_change": None,
                "retail_sentiment": None
            }
        }

    def get_data_for_technical_analysis(self) -> Dict:
        """
        获取技术分析所需的数据
        """
        return self.nasdaq_fetcher.get_data_for_technical_analysis()

def test_integrated_fetcher():
    """测试整合数据获取器"""
    fetcher = IntegratedDataFetcher()

    print("\n" + "=" * 60)
    print("整合数据获取器测试")
    print("=" * 60)

    # 获取情绪分析数据（完整版）
    print("\n1. 获取情绪分析数据（含市场关联数据）...")
    sentiment_data = fetcher.get_data_for_sentiment_analysis()

    print(f"   当前价格: ${sentiment_data['price_data']['current_price']}")
    print(f"   价格变动: {sentiment_data['price_data']['price_change_1d']:+.2f} ({sentiment_data['price_data']['price_change_pct']:+.2f}%)")
    print(f"   52周位置: {sentiment_data['price_data']['price_position']*100:.1f}%")

    print("\n   关联市场数据:")
    cm = sentiment_data['correlated_markets']
    print(f"     DXY美元指数: {cm['dxy']['value']} ({cm['dxy']['change_pct']:+.2f}%)")
    print(f"     VIX恐慌指数: {cm['vix']['value']} ({cm['vix']['change_pct']:+.2f}%)")
    print(f"     黄金估算价: ${cm['gold_futures']['price']}")
    print(f"     10年收益率: {cm['ten_year_yield']['value']}%")

    print("\n   金银比:")
    gsr = sentiment_data['gold_silver_ratio']
    print(f"     当前比值: {gsr['current']}")
    print(f"     评估: {gsr['interpretation']}")

    print("\n   恐惧贪婪指数:")
    fg = sentiment_data['fear_greed']
    print(f"     指数值: {fg['index_value']} ({fg['category']})")

    print("\n   资金流向估算:")
    ff = sentiment_data['fund_flows']
    print(f"     趋势: {ff.get('flow_estimate', 'N/A')}")
    print(f"     5日价格变动: {ff.get('price_change_5d_pct', 0):+.2f}%")

    print("\n2. 当前版本不再生成 AI 分析输入文件。")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_integrated_fetcher()

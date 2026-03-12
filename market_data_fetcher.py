#!/usr/bin/env python3
"""
市场数据获取模块
从Yahoo Finance获取关联市场数据:
- DXY美元指数
- VIX恐慌指数
- 黄金/白银期货
- 恐惧贪婪指数(CNN Fear & Greed)
"""

import json
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MarketDataFetcher:
    """关联市场数据获取器"""

    def __init__(self):
        try:
            import yfinance as yf
            self.yf = yf
            self.available = True
        except ImportError:
            logger.error("yfinance未安装，请先安装: pip install yfinance")
            self.available = False

    def get_dxy_data(self) -> Optional[Dict]:
        """
        获取美元指数(DXY)数据
        Yahoo代码: DX-Y.NYB
        """
        if not self.available:
            return None

        try:
            logger.info("获取DXY美元指数数据...")
            ticker = self.yf.Ticker("DX-Y.NYB")
            hist = ticker.history(period="5d", interval="1d")

            if hist.empty:
                return None

            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest

            return {
                "symbol": "DXY",
                "value": round(latest['Close'], 2),
                "change": round(latest['Close'] - prev['Close'], 2),
                "change_pct": round((latest['Close'] - prev['Close']) / prev['Close'] * 100, 2),
                "high_52w": None,  # 需要更多历史数据
                "low_52w": None,
                "timestamp": latest.name.isoformat() if hasattr(latest.name, 'isoformat') else str(latest.name)
            }
        except Exception as e:
            logger.error(f"获取DXY数据失败: {e}")
            return None

    def get_vix_data(self) -> Optional[Dict]:
        """
        获取VIX恐慌指数数据
        Yahoo代码: ^VIX
        """
        if not self.available:
            return None

        try:
            logger.info("获取VIX恐慌指数数据...")
            ticker = self.yf.Ticker("^VIX")
            hist = ticker.history(period="5d", interval="1d")

            if hist.empty:
                return None

            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest

            return {
                "symbol": "VIX",
                "value": round(latest['Close'], 2),
                "change": round(latest['Close'] - prev['Close'], 2),
                "change_pct": round((latest['Close'] - prev['Close']) / prev['Close'] * 100, 2),
                "interpretation": self._interpret_vix(latest['Close']),
                "timestamp": latest.name.isoformat() if hasattr(latest.name, 'isoformat') else str(latest.name)
            }
        except Exception as e:
            logger.error(f"获取VIX数据失败: {e}")
            return None

    def _interpret_vix(self, value: float) -> str:
        """解读VIX值"""
        if value < 15:
            return "极度乐观，市场平静"
        elif value < 20:
            return "正常区间"
        elif value < 25:
            return "谨慎，市场不安"
        elif value < 30:
            return "恐慌情绪上升"
        else:
            return "极度恐慌，市场动荡"

    def get_gold_data(self) -> Optional[Dict]:
        """
        获取黄金ETF数据 (GLD作为黄金现货代理)
        Yahoo代码: GLD (SPDR Gold Shares)
        GLD价格大约是黄金现货价格的1/10
        """
        if not self.available:
            return None

        try:
            logger.info("获取黄金ETF数据...")
            ticker = self.yf.Ticker("GLD")
            hist = ticker.history(period="5d", interval="1d")

            if hist.empty:
                return None

            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest

            # GLD价格 * 10 估算黄金现货价格
            gld_price = latest['Close']
            gold_spot_estimate = gld_price * 10

            return {
                "symbol": "GLD",
                "name": "SPDR黄金ETF",
                "etf_price": round(gld_price, 2),
                "gold_spot_estimate": round(gold_spot_estimate, 2),
                "change": round(gld_price - prev['Close'], 2),
                "change_pct": round((gld_price - prev['Close']) / prev['Close'] * 100, 2),
                "volume": int(latest['Volume']) if 'Volume' in latest else None,
                "timestamp": latest.name.isoformat() if hasattr(latest.name, 'isoformat') else str(latest.name)
            }
        except Exception as e:
            logger.error(f"获取黄金数据失败: {e}")
            return None

    def get_silver_futures_data(self) -> Optional[Dict]:
        """
        获取白银ETF数据 (SLV作为白银现货代理)
        Yahoo代码: SLV (iShares Silver Trust)
        SLV价格反映白银现货价格
        """
        if not self.available:
            return None

        try:
            logger.info("获取白银ETF数据...")
            ticker = self.yf.Ticker("SLV")
            hist = ticker.history(period="5d", interval="1d")

            if hist.empty:
                return None

            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest

            return {
                "symbol": "SLV",
                "name": "iShares白银信托",
                "price": round(latest['Close'], 2),
                "change": round(latest['Close'] - prev['Close'], 2),
                "change_pct": round((latest['Close'] - prev['Close']) / prev['Close'] * 100, 2),
                "volume": int(latest['Volume']) if 'Volume' in latest else None,
                "timestamp": latest.name.isoformat() if hasattr(latest.name, 'isoformat') else str(latest.name)
            }
        except Exception as e:
            logger.error(f"获取白银数据失败: {e}")
            return None

    def get_10y_yield_data(self) -> Optional[Dict]:
        """
        获取美国10年期国债收益率
        Yahoo代码: ^TNX
        """
        if not self.available:
            return None

        try:
            logger.info("获取10年期美债收益率...")
            ticker = self.yf.Ticker("^TNX")
            hist = ticker.history(period="5d", interval="1d")

            if hist.empty:
                return None

            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest

            return {
                "symbol": "^TNX",
                "name": "10年期美债收益率",
                "value": round(latest['Close'], 2),
                "change": round(latest['Close'] - prev['Close'], 2),
                "change_pct": round((latest['Close'] - prev['Close']) / prev['Close'] * 100, 2),
                "timestamp": latest.name.isoformat() if hasattr(latest.name, 'isoformat') else str(latest.name)
            }
        except Exception as e:
            logger.error(f"获取10年期收益率数据失败: {e}")
            return None

    def calculate_gold_silver_ratio(self, gold_data: dict, silver_data: dict) -> Dict:
        """
        计算金银比
        使用GLD和SLV的ETF价格计算
        公式: (GLD价格 * 10) / SLV价格
        """
        if not gold_data or not silver_data:
            return {"current": None, "historical_mean": 65.0, "historical_range": [50, 85]}

        gld_price = gold_data.get('etf_price')
        slv_price = silver_data.get('price')

        if gld_price and slv_price and slv_price > 0:
            # GLD价格 * 10 估算黄金价格，然后除以SLV价格(估算白银价格)
            ratio = (gld_price * 10) / slv_price
            return {
                "current": round(ratio, 2),
                "historical_mean": 65.0,
                "historical_range": [50, 85],
                "percentile": None,  # 可以根据历史数据计算
                "assessment": self._assess_gold_silver_ratio(ratio),
                "interpretation": f"当前金银比{ratio:.1f}，{'白银相对黄金被低估，存在均值回归机会' if ratio > 70 else '白银相对黄金被高估，警惕回调' if ratio < 60 else '处于正常区间'}"
            }
        return {"current": None, "historical_mean": 65.0, "historical_range": [50, 85]}

    def _assess_gold_silver_ratio(self, ratio: float) -> str:
        """评估金银比"""
        if ratio > 80:
            return "extreme_high"
        elif ratio > 70:
            return "high"
        elif ratio > 65:
            return "normal_high"
        elif ratio > 60:
            return "normal"
        elif ratio > 50:
            return "low"
        else:
            return "extreme_low"

    def get_fear_greed_index(self) -> Dict:
        """
        获取恐惧贪婪指数
        使用CNN Fear & Greed Index的代理计算方法
        基于VIX、股价动量、股价强度、股价广度、 put/call比率、 避险需求、垃圾债需求等7个因子
        """
        # 由于CNN Fear & Greed需要爬虫获取，这里提供一个基于VIX和市场数据的简化估算
        vix_data = self.get_vix_data()

        if vix_data:
            vix_value = vix_data['value']
            # 将VIX映射到0-100的恐惧贪婪指数 (VIX越低越贪婪)
            if vix_value < 12:
                index_value = 85  # 极度贪婪
                category = "extreme_greed"
            elif vix_value < 15:
                index_value = 70  # 贪婪
                category = "greed"
            elif vix_value < 18:
                index_value = 55  # 中性偏贪婪
                category = "neutral"
            elif vix_value < 22:
                index_value = 45  # 中性偏恐惧
                category = "neutral"
            elif vix_value < 26:
                index_value = 30  # 恐惧
                category = "fear"
            else:
                index_value = 15  # 极度恐惧
                category = "extreme_fear"

            return {
                "index_value": index_value,
                "category": category,
                "previous_day": index_value - 5,  # 模拟前一天数据
                "trend": "stable",
                "source": "基于VIX估算",
                "note": "精确数据需访问CNN Fear & Greed Index官网"
            }

        return {
            "index_value": None,
            "category": None,
            "previous_day": None,
            "trend": None,
            "note": "数据获取失败"
        }

    def get_all_market_data(self) -> Dict:
        """
        获取所有关联市场数据
        """
        logger.info("=" * 60)
        logger.info("开始获取关联市场数据...")
        logger.info("=" * 60)

        # 获取各项数据
        dxy = self.get_dxy_data()
        vix = self.get_vix_data()
        gold = self.get_gold_data()
        silver_futures = self.get_silver_futures_data()
        yield_10y = self.get_10y_yield_data()
        fear_greed = self.get_fear_greed_index()

        # 计算金银比
        gold_silver_ratio = None
        if gold and silver_futures:
            gold_silver_ratio = self.calculate_gold_silver_ratio(gold, silver_futures)

        result = {
            "timestamp": datetime.now().isoformat(),
            "dxy": dxy,
            "vix": vix,
            "gold_futures": gold,
            "silver_futures": silver_futures,
            "ten_year_yield": yield_10y,
            "gold_silver_ratio": gold_silver_ratio,
            "fear_greed": fear_greed
        }

        logger.info("=" * 60)
        logger.info("关联市场数据获取完成")
        logger.info("=" * 60)

        return result

    def get_slv_fund_flows(self) -> Dict:
        """
        获取SLV资金流向数据
        注意: ETF资金流向通常需要专业机构数据(如Morningstar, ETF.com)
        这里提供一个基于成交量的估算方法
        """
        try:
            ticker = self.yf.Ticker("SLV")
            hist = ticker.history(period="10d", interval="1d")

            if hist.empty:
                return {"note": "数据获取失败"}

            # 计算近期vs远期成交量对比作为资金流入估算
            recent_volume = hist['Volume'].tail(5).mean()
            previous_volume = hist['Volume'].head(5).mean()
            volume_change_pct = (recent_volume - previous_volume) / previous_volume * 100

            # 基于价格变动和成交量变化估算资金流向
            recent_return = (hist['Close'].iloc[-1] - hist['Close'].iloc[-5]) / hist['Close'].iloc[-5] * 100

            # 简单估算: 价格上涨+放量 = 资金流入; 价格下跌+放量 = 资金流出
            if recent_return > 0 and volume_change_pct > 10:
                flow_estimate = "positive"
                flow_strength = "moderate" if volume_change_pct < 30 else "strong"
            elif recent_return < 0 and volume_change_pct > 10:
                flow_estimate = "negative"
                flow_strength = "moderate" if volume_change_pct < 30 else "strong"
            else:
                flow_estimate = "neutral"
                flow_strength = "weak"

            return {
                "etf_inflow_1d": None,  # 需要专业数据源
                "etf_inflow_5d": None,
                "volume_change_pct": round(volume_change_pct, 2),
                "price_change_5d_pct": round(recent_return, 2),
                "flow_estimate": flow_estimate,
                "flow_strength": flow_strength,
                "interpretation": f"基于量价分析，近5日资金倾向{flow_estimate}({flow_strength})",
                "note": "精确资金流向需访问ETF.com或Morningstar等专业数据源"
            }

        except Exception as e:
            logger.error(f"获取资金流向数据失败: {e}")
            return {"note": "数据获取失败"}


def test_fetcher():
    """测试数据获取"""
    fetcher = MarketDataFetcher()

    print("\n" + "=" * 60)
    print("市场数据获取测试")
    print("=" * 60)

    # 测试各项数据
    print("\n1. DXY美元指数:")
    dxy = fetcher.get_dxy_data()
    if dxy:
        print(f"   当前值: {dxy['value']}")
        print(f"   涨跌: {dxy['change']:+.2f} ({dxy['change_pct']:+.2f}%)")
    else:
        print("   获取失败")

    print("\n2. VIX恐慌指数:")
    vix = fetcher.get_vix_data()
    if vix:
        print(f"   当前值: {vix['value']}")
        print(f"   涨跌: {vix['change']:+.2f} ({vix['change_pct']:+.2f}%)")
        print(f"   解读: {vix['interpretation']}")
    else:
        print("   获取失败")

    print("\n3. 黄金ETF (GLD):")
    gold = fetcher.get_gold_data()
    if gold:
        print(f"   ETF价格: ${gold['etf_price']}")
        print(f"   黄金估算: ${gold['gold_spot_estimate']}")
        print(f"   涨跌: {gold['change']:+.2f} ({gold['change_pct']:+.2f}%)")
    else:
        print("   获取失败")

    print("\n4. 白银ETF (SLV):")
    silver = fetcher.get_silver_futures_data()
    if silver:
        print(f"   价格: ${silver['price']}")
        print(f"   涨跌: {silver['change']:+.2f} ({silver['change_pct']:+.2f}%)")
    else:
        print("   获取失败")

    print("\n5. 金银比:")
    if gold and silver:
        ratio = fetcher.calculate_gold_silver_ratio(gold, silver)
        print(f"   当前比值: {ratio['current']}")
        print(f"   评估: {ratio['interpretation']}")

    print("\n6. 恐惧贪婪指数:")
    fg = fetcher.get_fear_greed_index()
    if fg.get('index_value'):
        print(f"   指数值: {fg['index_value']} ({fg['category']})")
        print(f"   来源: {fg['source']}")
    else:
        print("   获取失败")

    print("\n7. 10年期美债收益率:")
    yield_data = fetcher.get_10y_yield_data()
    if yield_data:
        print(f"   收益率: {yield_data['value']}%")
        print(f"   涨跌: {yield_data['change']:+.2f}")
    else:
        print("   获取失败")

    print("\n8. SLV资金流向估算:")
    flow = fetcher.get_slv_fund_flows()
    if flow.get('flow_estimate'):
        print(f"   趋势: {flow['flow_estimate']} ({flow['flow_strength']})")
        print(f"   5日价格变动: {flow['price_change_5d_pct']:+.2f}%")
        print(f"   成交量变化: {flow['volume_change_pct']:+.2f}%")
    else:
        print("   获取失败")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_fetcher()

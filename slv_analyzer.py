#!/usr/bin/env python3
"""
SLV 白银ETF 本地规则分析系统 V3
================================
整合数据采集、实时技术指标和双维度交易建议。

使用方法:
    python slv_analyzer.py --mode full      # 生成完整版报告（默认）
    python slv_analyzer.py --mode brief     # 生成简洁版报告
    python slv_analyzer.py -m brief         # 简写形式

主要功能:
    1. 实时技术指标计算（RSI / MACD / ATR / 布林带等）
    2. 双维度交易建议：
       - 短期建议：日内 / 短线交易（1-5天）
       - 长期建议：趋势 / 持仓交易（1-4周）
    3. 基于规则的综合评级与市场情绪总结

输出:
    - reports/slv_analysis_report_*.md  (最终报告)
"""

import argparse
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Tuple
from dataclasses import dataclass

# 导入模块
from integrated_data_fetcher import IntegratedDataFetcher
from data_fetcher_v2 import SLVDataFetcher


@dataclass
class TechnicalIndicators:
    """技术指标集合"""
    rsi: float
    macd: float
    macd_signal: float
    atr: float
    atr_5d: float  # 5日ATR用于短期
    sma5: float
    sma10: float
    sma20: float
    sma50: float
    sma200: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    volume_ratio: float
    trend_short: str  # 短期趋势
    trend_long: str   # 长期趋势


@dataclass
class TradingRecommendation:
    """交易建议"""
    signal_type: str  # STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
    score: float
    position_size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    timeframe: str  # short_term / long_term
    rationale: str


class ReportGenerator:
    """报告生成器"""

    def __init__(self, template_path: str = "templates/report_template.md"):
        self.template_path = Path(template_path)
        self.template = self._load_template()

    def _load_template(self) -> str:
        """加载报告模板"""
        if not self.template_path.exists():
            return self._get_default_template()
        return self.template_path.read_text(encoding='utf-8')

    def _get_default_template(self) -> str:
        """默认模板"""
        return """# SLV 白银ETF 分析报告

**报告生成时间**: {{report_date}}
**数据截止日期**: {{data_date}}
**分析方式**: 本地规则模型 + 实时技术指标

---

## 执行摘要

| 指标 | 数值 |
|------|------|
| 当前价格 | ${{current_price}} |
| 日涨跌 | {{price_change}} ({{price_change_pct}}%) |
| 成交量 | {{volume}} |
| 综合评级 | {{overall_rating}} |
| 短期建议 | {{short_term_signal}} |
| 长期建议 | {{long_term_signal}} |

**核心观点**: {{key_insight}}

---

*详细分析内容基于本地规则计算结果填充*

---
**免责声明**: 本报告仅供参考，不构成投资建议。
"""

    def generate(self, variables: Dict) -> str:
        """使用变量填充模板生成报告"""
        report = self.template
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in report:
                report = report.replace(placeholder, str(value) if value is not None else "N/A")
        return report


class SLVAnalyzer:
    """SLV分析主控类 V3（本地规则 + 实时指标）"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = Path(data_dir)
        self.fetcher = IntegratedDataFetcher(data_dir=data_dir)
        self.fetcher_v2 = SLVDataFetcher(data_dir=data_dir)
        self.report_generator = ReportGenerator(
            template_path=self.data_dir / "templates/report_template.md"
        )

        # 实时指标
        self.current_price = 0.0
        self.indicators = None
        self.short_term_rec = None
        self.long_term_rec = None

    def cleanup_old_reports(self, keep_days: int = 3):
        """清理旧报告文件"""
        reports_dir = self.data_dir / "reports"
        if not reports_dir.exists():
            return

        cutoff_date = datetime.now() - timedelta(days=keep_days)
        deleted_count = 0

        try:
            for file_path in reports_dir.iterdir():
                if file_path.is_file() and file_path.name.startswith("slv_analysis_report_"):
                    try:
                        date_str = file_path.name.split('_')[3]
                        file_date = datetime.strptime(date_str, "%Y%m%d")

                        if file_date < cutoff_date:
                            file_path.unlink()
                            deleted_count += 1
                    except (IndexError, ValueError):
                        continue

            if deleted_count > 0:
                print(f"🧹 已清理 {deleted_count} 个超过 {keep_days} 天的旧报告")
        except Exception as e:
            print(f"⚠️  清理旧报告时出错: {e}")

    def collect_data(self) -> Dict:
        """收集所有数据"""
        print("📊 正在收集数据...")
        complete_data = self.fetcher.get_complete_data()
        return {
            "technical": complete_data.get('nasdaq_data'),
            "market": complete_data.get('market_data'),
            "fund_flows": complete_data.get('fund_flows'),
            "timestamp": complete_data.get('timestamp', datetime.now().isoformat())
        }

    def calculate_realtime_indicators(self, hist_df: pd.DataFrame, quote: Dict) -> TechnicalIndicators:
        """计算实时技术指标"""
        if hist_df is None or hist_df.empty:
            return TechnicalIndicators(
                rsi=50, macd=0, macd_signal=0, atr=0, atr_5d=0,
                sma5=0, sma10=0, sma20=0, sma50=0, sma200=0,
                bb_upper=0, bb_middle=0, bb_lower=0, volume_ratio=1.0,
                trend_short='unknown', trend_long='unknown'
            )

        closes = hist_df['Close'].values
        highs = hist_df['High'].values
        lows = hist_df['Low'].values
        volumes = hist_df['Volume'].values

        # 确保数据足够
        if len(closes) < 50:
            last_price = quote.get('last_price', closes[-1] if len(closes) > 0 else 0)
            return TechnicalIndicators(
                rsi=50, macd=0, macd_signal=0, atr=last_price*0.02, atr_5d=last_price*0.015,
                sma5=last_price, sma10=last_price, sma20=last_price, sma50=last_price, sma200=last_price,
                bb_upper=last_price*1.05, bb_middle=last_price, bb_lower=last_price*0.95,
                volume_ratio=1.0, trend_short='unknown', trend_long='unknown'
            )

        # 当前价格
        current_price = quote.get('last_price', closes[-1])

        # RSI
        rsi = self._calculate_rsi(closes, 14)

        # MACD
        macd, macd_signal = self._calculate_macd(closes)

        # ATR (14日和5日)
        atr = self._calculate_atr(highs, lows, closes, 14)
        atr_5d = self._calculate_atr(highs, lows, closes, 5)

        # SMA
        sma5 = np.mean(closes[-5:]) if len(closes) >= 5 else current_price
        sma10 = np.mean(closes[-10:]) if len(closes) >= 10 else current_price
        sma20 = np.mean(closes[-20:]) if len(closes) >= 20 else current_price
        sma50 = np.mean(closes[-50:]) if len(closes) >= 50 else current_price
        sma200 = np.mean(closes[-200:]) if len(closes) >= 200 else sma50

        # Bollinger Bands (20日)
        std20 = np.std(closes[-20:]) if len(closes) >= 20 else current_price * 0.02
        bb_middle = sma20
        bb_upper = bb_middle + 2 * std20
        bb_lower = bb_middle - 2 * std20

        # 成交量比率
        current_volume = quote.get('volume', volumes[-1] if len(volumes) > 0 else 0)
        if current_volume is None:
            current_volume = volumes[-1] if len(volumes) > 0 else 0
        avg_volume_20d = np.mean(volumes[-20:]) if len(volumes) >= 20 else current_volume
        volume_ratio = current_volume / avg_volume_20d if avg_volume_20d > 0 else 1.0

        # 短期趋势 (5日 vs 10日)
        if sma5 > sma10 * 1.01:
            trend_short = 'up'
        elif sma5 < sma10 * 0.99:
            trend_short = 'down'
        else:
            trend_short = 'sideways'

        # 长期趋势 (20日 vs 50日)
        if sma20 > sma50 * 1.02:
            trend_long = 'up'
        elif sma20 < sma50 * 0.98:
            trend_long = 'down'
        else:
            trend_long = 'sideways'

        return TechnicalIndicators(
            rsi=rsi,
            macd=macd,
            macd_signal=macd_signal,
            atr=atr,
            atr_5d=atr_5d,
            sma5=sma5,
            sma10=sma10,
            sma20=sma20,
            sma50=sma50,
            sma200=sma200,
            bb_upper=bb_upper,
            bb_middle=bb_middle,
            bb_lower=bb_lower,
            volume_ratio=volume_ratio,
            trend_short=trend_short,
            trend_long=trend_long
        )

    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """计算 RSI"""
        if len(prices) < period + 1:
            return 50.0

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gains = np.mean(gains[-period:])
        avg_losses = np.mean(losses[-period:])

        if avg_losses == 0:
            return 100.0

        rs = avg_gains / avg_losses
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_macd(self, prices: np.ndarray) -> Tuple[float, float]:
        """计算 MACD"""
        if len(prices) < 26:
            return 0.0, 0.0

        exp12 = pd.Series(prices).ewm(span=12).mean()
        exp26 = pd.Series(prices).ewm(span=26).mean()
        macd_series = exp12 - exp26
        signal_series = macd_series.ewm(span=9).mean()

        return macd_series.iloc[-1], signal_series.iloc[-1]

    def _calculate_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """计算 ATR"""
        if len(highs) < period + 1:
            return 0.0

        high_low = highs[-period:] - lows[-period:]
        high_close = np.abs(highs[-period:] - closes[-period-1:-1])
        low_close = np.abs(lows[-period:] - closes[-period-1:-1])

        tr = np.maximum(np.maximum(high_low, high_close), low_close)
        atr = np.mean(tr)
        return atr

    def generate_short_term_recommendation(self, price: float, ind: TechnicalIndicators) -> TradingRecommendation:
        """生成短期交易建议（1-5天）"""
        score = 0.0
        rationale_parts = []

        # RSI 信号（短期更敏感）
        if ind.rsi < 30:
            score += 0.35
            rationale_parts.append(f"RSI超卖({ind.rsi:.1f})")
        elif ind.rsi > 70:
            score -= 0.35
            rationale_parts.append(f"RSI超买({ind.rsi:.1f})")
        elif ind.rsi < 45:
            score += 0.15
            rationale_parts.append(f"RSI偏低({ind.rsi:.1f})")
        elif ind.rsi > 55:
            score -= 0.15
            rationale_parts.append(f"RSI偏高({ind.rsi:.1f})")

        # MACD 信号
        if ind.macd > ind.macd_signal:
            score += 0.25
            rationale_parts.append("MACD金叉")
        else:
            score -= 0.25
            rationale_parts.append("MACD死叉")

        # 布林带信号
        if price < ind.bb_lower:
            score += 0.25
            rationale_parts.append("价格跌破下轨")
        elif price > ind.bb_upper:
            score -= 0.25
            rationale_parts.append("价格突破上轨")

        # 短期趋势
        if ind.trend_short == 'up':
            score += 0.15
            rationale_parts.append("短期趋势向上")
        elif ind.trend_short == 'down':
            score -= 0.15
            rationale_parts.append("短期趋势向下")

        # 成交量
        if ind.volume_ratio > 1.5:
            rationale_parts.append(f"放量({ind.volume_ratio:.1f}x)")

        # 确定信号
        signal_type = self._score_to_signal(score)
        position_sizes = {
            'STRONG_BUY': 0.60, 'BUY': 0.40, 'HOLD': 0.0,
            'SELL': 0.20, 'STRONG_SELL': 0.05
        }

        # 短期使用更紧的止损（1.5倍ATR）
        stop_loss = price - ind.atr_5d * 1.5 if ind.atr_5d > 0 else price * 0.97
        take_profit = price + ind.atr_5d * 2.0 if ind.atr_5d > 0 else price * 1.05

        risk = price - stop_loss
        reward = take_profit - price
        rr_ratio = reward / risk if risk > 0 else 0

        return TradingRecommendation(
            signal_type=signal_type,
            score=round(score, 2),
            position_size=position_sizes.get(signal_type, 0),
            entry_price=price,
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            risk_reward_ratio=round(rr_ratio, 2),
            timeframe="short_term",
            rationale=" | ".join(rationale_parts) if rationale_parts else "技术面中性"
        )

    def generate_long_term_recommendation(self, price: float, ind: TechnicalIndicators) -> TradingRecommendation:
        """生成长期交易建议（1-4周）"""
        score = 0.0
        rationale_parts = []

        # 长期趋势权重更高
        if ind.trend_long == 'up':
            score += 0.40
            rationale_parts.append("长期趋势向上")
        elif ind.trend_long == 'down':
            score -= 0.40
            rationale_parts.append("长期趋势向下")
        else:
            rationale_parts.append("长期趋势震荡")

        # 价格在均线系统的位置
        if price > ind.sma20 > ind.sma50:
            score += 0.25
            rationale_parts.append("多头排列")
        elif price < ind.sma20 < ind.sma50:
            score -= 0.25
            rationale_parts.append("空头排列")

        # RSI（长期视角）
        if ind.rsi < 35:
            score += 0.20
            rationale_parts.append("RSI低位")
        elif ind.rsi > 65:
            score -= 0.20
            rationale_parts.append("RSI高位")

        # MACD 趋势确认
        if ind.macd > 0 and ind.macd > ind.macd_signal:
            score += 0.15
            rationale_parts.append("MACD多头")
        elif ind.macd < 0 and ind.macd < ind.macd_signal:
            score -= 0.15
            rationale_parts.append("MACD空头")

        # 200日均线（牛熊分界线）
        if price > ind.sma200:
            score += 0.10
            rationale_parts.append("价格在200日均线上方")
        else:
            score -= 0.10
            rationale_parts.append("价格在200日均线下方")

        # 确定信号
        signal_type = self._score_to_signal(score)
        position_sizes = {
            'STRONG_BUY': 0.80, 'BUY': 0.60, 'HOLD': 0.20,
            'SELL': 0.15, 'STRONG_SELL': 0.05
        }

        # 长期使用更宽的止损（2.5倍ATR）
        stop_loss = price - ind.atr * 2.5 if ind.atr > 0 else price * 0.92
        take_profit = price + ind.atr * 4.0 if ind.atr > 0 else price * 1.12

        risk = price - stop_loss
        reward = take_profit - price
        rr_ratio = reward / risk if risk > 0 else 0

        return TradingRecommendation(
            signal_type=signal_type,
            score=round(score, 2),
            position_size=position_sizes.get(signal_type, 0),
            entry_price=price,
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            risk_reward_ratio=round(rr_ratio, 2),
            timeframe="long_term",
            rationale=" | ".join(rationale_parts) if rationale_parts else "趋势中性"
        )

    def _score_to_signal(self, score: float) -> str:
        """评分转换为信号类型"""
        if score >= 0.60:
            return 'STRONG_BUY'
        elif score >= 0.25:
            return 'BUY'
        elif score >= -0.15:
            return 'HOLD'
        elif score >= -0.40:
            return 'SELL'
        else:
            return 'STRONG_SELL'

    def print_realtime_analysis(self):
        """打印实时技术分析报告"""
        print("\n" + "="*70)
        print("📊 实时技术指标分析")
        print("="*70)

        # 获取实时数据
        print("\n正在获取 SLV 实时数据...")
        quote = self.fetcher_v2.get_current_quote()
        hist_df = self.fetcher_v2.load_historical_data()

        if not quote or hist_df is None or hist_df.empty:
            print("❌ 数据获取失败")
            return

        self.current_price = quote.get('last_price', 0)
        prev_close = quote.get('previous_close', self.current_price)

        # 计算指标
        self.indicators = self.calculate_realtime_indicators(hist_df, quote)

        # 打印基本信息
        volume = quote.get('volume', 0)
        if volume is None:
            volume = 0
        
        # 判断是否为夜盘价格
        is_extended = quote.get('is_extended_hours', False)
        price_type = quote.get('price_type', 'unknown')
        yahoo_fallback = quote.get('yahoo_fallback', False)
        yahoo_status = quote.get('yahoo_status', 'unknown')
        
        # 价格类型中文映射
        price_type_cn = {
            'regular_hours': '常规交易时间',
            'pre_market': '盘前交易',
            'post_market': '盘后交易',
            'extended_hours': '延长时间',
            'unknown': '未知'
        }
        
        print(f"\n📈 基本信息")
        print("-"*70)
        print(f"当前价格: ${self.current_price:.2f}")
        print(f"涨跌: {self.current_price - prev_close:+.2f} ({((self.current_price - prev_close)/prev_close*100) if prev_close else 0:+.2f}%)")
        print(f"成交量: {volume:,}")
        print(f"数据源: {quote.get('price_source', 'unknown')}")
        print(f"价格类型: {price_type_cn.get(price_type, price_type)} {'🌙' if is_extended else '☀️'}")
        if is_extended:
            print(f"⚠️  注意: 当前为夜盘/延长时间价格")
        if yahoo_fallback:
            print(f"⚠️  注意: Yahoo数据获取失败 ({yahoo_status})，已使用备用数据源")

        # 打印技术指标
        ind = self.indicators
        print(f"\n📉 技术指标")
        print("-"*70)
        print(f"RSI(14): {ind.rsi:.2f} {'⚠️ 超卖' if ind.rsi < 30 else '⚠️ 超买' if ind.rsi > 70 else '✓ 中性'}")
        print(f"MACD: {ind.macd:.4f} (Signal: {ind.macd_signal:.4f}) {'✓ 金叉' if ind.macd > ind.macd_signal else '✗ 死叉'}")
        print(f"ATR(14): ${ind.atr:.3f} | ATR(5): ${ind.atr_5d:.3f}")
        print(f"SMA5: ${ind.sma5:.2f} | SMA10: ${ind.sma10:.2f} | SMA20: ${ind.sma20:.2f}")
        print(f"SMA50: ${ind.sma50:.2f} | SMA200: ${ind.sma200:.2f}")
        print(f"布林带: ${ind.bb_lower:.2f} - ${ind.bb_middle:.2f} - ${ind.bb_upper:.2f}")
        print(f"成交量比: {ind.volume_ratio:.2f}x {'🔥 放量' if ind.volume_ratio > 1.5 else '💤 缩量' if ind.volume_ratio < 0.8 else '✓ 正常'}")
        print(f"短期趋势: {ind.trend_short.upper()} | 长期趋势: {ind.trend_long.upper()}")

        # 生成双维度建议
        self.short_term_rec = self.generate_short_term_recommendation(self.current_price, ind)
        self.long_term_rec = self.generate_long_term_recommendation(self.current_price, ind)

        # 打印短期建议
        print(f"\n⚡ 短期交易建议 (1-5天)")
        print("-"*70)
        print(f"信号: {self._format_signal(self.short_term_rec.signal_type)}")
        print(f"综合得分: {self.short_term_rec.score:+.2f}")
        print(f"建议仓位: {self.short_term_rec.position_size:.0%}")
        print(f"入场: ${self.short_term_rec.entry_price:.2f}")
        print(f"止损: ${self.short_term_rec.stop_loss:.2f} (1.5×ATR5)")
        print(f"止盈: ${self.short_term_rec.take_profit:.2f} (2.0×ATR5)")
        print(f"风险收益比: 1:{self.short_term_rec.risk_reward_ratio:.1f}")
        print(f"理由: {self.short_term_rec.rationale}")

        # 打印长期建议
        print(f"\n📈 长期交易建议 (1-4周)")
        print("-"*70)
        print(f"信号: {self._format_signal(self.long_term_rec.signal_type)}")
        print(f"综合得分: {self.long_term_rec.score:+.2f}")
        print(f"建议仓位: {self.long_term_rec.position_size:.0%}")
        print(f"入场: ${self.long_term_rec.entry_price:.2f}")
        print(f"止损: ${self.long_term_rec.stop_loss:.2f} (2.5×ATR14)")
        print(f"止盈: ${self.long_term_rec.take_profit:.2f} (4.0×ATR14)")
        print(f"风险收益比: 1:{self.long_term_rec.risk_reward_ratio:.1f}")
        print(f"理由: {self.long_term_rec.rationale}")

        print("\n" + "="*70)

    def _format_signal(self, signal: str) -> str:
        """格式化信号显示"""
        emojis = {
            'STRONG_BUY': '🟢🟢 强烈买入',
            'BUY': '🟢 买入',
            'HOLD': '🟡 观望',
            'SELL': '🔴 卖出',
            'STRONG_SELL': '🔴🔴 强烈卖出'
        }
        return emojis.get(signal, signal)

    def _signal_to_numeric(self, signal: str) -> int:
        """将离散信号转换为便于聚合的数值"""
        mapping = {
            'STRONG_BUY': 2,
            'BUY': 1,
            'HOLD': 0,
            'SELL': -1,
            'STRONG_SELL': -2,
        }
        return mapping.get(signal, 0)

    def _combine_signals(self) -> str:
        """长周期信号权重更高，用于生成综合评级"""
        if not self.short_term_rec or not self.long_term_rec:
            return 'HOLD'

        combined = (
            self._signal_to_numeric(self.short_term_rec.signal_type) * 0.4 +
            self._signal_to_numeric(self.long_term_rec.signal_type) * 0.6
        )

        if combined >= 1.5:
            return 'STRONG_BUY'
        if combined >= 0.5:
            return 'BUY'
        if combined > -0.5:
            return 'HOLD'
        if combined > -1.5:
            return 'SELL'
        return 'STRONG_SELL'

    def _estimate_confidence(self) -> int:
        """根据趋势一致性和指标偏离度给出简单置信度"""
        if not self.indicators:
            return 50

        confidence = 50
        if abs(self.indicators.rsi - 50) >= 15:
            confidence += 10
        if abs(self.indicators.macd - self.indicators.macd_signal) >= 0.5:
            confidence += 10
        if self.indicators.trend_short == self.indicators.trend_long and self.indicators.trend_short != 'sideways':
            confidence += 15
        if self.indicators.volume_ratio >= 1.2:
            confidence += 5
        return min(confidence, 90)

    def _summarize_market_sentiment(self, market_snapshot: Dict) -> Dict:
        """用关联市场数据生成本地情绪摘要"""
        market_data = market_snapshot.get('market') or {}
        fund_flows = market_snapshot.get('fund_flows') or {}

        score = 50
        reasons = []

        dxy_change = (market_data.get('dxy') or {}).get('change_pct')
        if dxy_change is not None:
            if dxy_change < 0:
                score += 5
                reasons.append("美元走弱，对贵金属偏利多")
            elif dxy_change > 0:
                score -= 5
                reasons.append("美元走强，对贵金属形成压制")

        gold_change = (market_data.get('gold_futures') or {}).get('change_pct')
        if gold_change is not None:
            if gold_change > 0:
                score += 5
                reasons.append("黄金同步走强，贵金属板块情绪改善")
            elif gold_change < 0:
                score -= 5
                reasons.append("黄金走弱，板块情绪偏谨慎")

        yield_change = (market_data.get('ten_year_yield') or {}).get('change_pct')
        if yield_change is not None:
            if yield_change < 0:
                score += 5
                reasons.append("美债收益率回落，贵金属估值压力缓和")
            elif yield_change > 0:
                score -= 5
                reasons.append("美债收益率上行，不利于无息资产")

        fear_greed = (market_data.get('fear_greed') or {}).get('category')
        if fear_greed in {'fear', 'extreme_fear'}:
            score += 3
            reasons.append("风险偏好回落，避险需求略有支撑")
        elif fear_greed in {'greed', 'extreme_greed'}:
            score -= 3
            reasons.append("风险偏好偏强，避险支撑减弱")

        flow_estimate = fund_flows.get('flow_estimate')
        if flow_estimate == 'positive':
            score += 10
            reasons.append("近5日量价结构显示资金偏流入")
        elif flow_estimate == 'negative':
            score -= 10
            reasons.append("近5日量价结构显示资金偏流出")

        score = max(0, min(score, 100))
        if score >= 60:
            sentiment = 'bullish'
        elif score <= 40:
            sentiment = 'bearish'
        else:
            sentiment = 'neutral'

        summary_text = "；".join(reasons[:3]) if reasons else "关联市场信号整体中性。"
        return {
            "overall_sentiment": sentiment,
            "sentiment_score": score,
            "confidence": 0.7,
            "summary_text": summary_text
        }

    def build_analysis_results(self, market_snapshot: Dict) -> Dict:
        """构建不依赖外部模型的本地分析结果"""
        overall_signal = self._combine_signals()
        confidence = self._estimate_confidence()
        sentiment_summary = self._summarize_market_sentiment(market_snapshot)

        short_signal = self.short_term_rec.signal_type if self.short_term_rec else 'HOLD'
        long_signal = self.long_term_rec.signal_type if self.long_term_rec else 'HOLD'
        key_observation = (
            f"短期{short_signal}，长期{long_signal}；"
            f"RSI {self.indicators.rsi:.1f}，"
            f"短期趋势 {self.indicators.trend_short}，长期趋势 {self.indicators.trend_long}。"
        ) if self.indicators else "技术指标数据不足。"

        return {
            "technical": {
                "summary": {
                    "overall_signal": overall_signal,
                    "confidence": confidence,
                    "key_observation": key_observation
                }
            },
            "sentiment": {
                "analysis_summary": sentiment_summary
            }
        }

    def generate_report(self, analysis_results: Dict, mode: str = "full") -> str:
        """生成最终报告"""
        print(f"\n📝 正在生成{('完整版' if mode == 'full' else '简洁版')}报告...")

        if mode == "brief":
            report = self._generate_brief_report(analysis_results)
        else:
            report = self._generate_full_report(analysis_results)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.data_dir / "reports" / f"slv_analysis_report_{timestamp}_{mode}.md"
        report_file.parent.mkdir(exist_ok=True)
        report_file.write_text(report, encoding='utf-8')

        print(f"✅ 报告已保存: {report_file}")
        return str(report_file)

    def _generate_brief_report(self, analysis_results: Dict) -> str:
        """生成简洁版报告"""
        tech = analysis_results.get('technical', {})
        sentiment = analysis_results.get('sentiment', {})

        tech_summary = tech.get('summary', {})
        sentiment_summary = sentiment.get('analysis_summary', {})

        now = datetime.now()

        # 信号emoji
        def signal_emoji(signal):
            return {
                'STRONG_BUY': '🟢🟢 强烈买入',
                'BUY': '🟢 买入',
                'HOLD': '🟡 观望',
                'SELL': '🔴 卖出',
                'STRONG_SELL': '🔴🔴 强烈卖出'
            }.get(signal, f'⚪ {signal}')

        short_signal = signal_emoji(self.short_term_rec.signal_type) if self.short_term_rec else 'N/A'
        short_size = f"{self.short_term_rec.position_size:.0%}" if self.short_term_rec else '0%'
        short_score = f"{self.short_term_rec.score:+.2f}" if self.short_term_rec else '0.00'
        short_sl = self.short_term_rec.stop_loss if self.short_term_rec else 0
        short_tp = self.short_term_rec.take_profit if self.short_term_rec else 0
        short_reason = self.short_term_rec.rationale if self.short_term_rec else 'N/A'

        long_signal = signal_emoji(self.long_term_rec.signal_type) if self.long_term_rec else 'N/A'
        long_size = f"{self.long_term_rec.position_size:.0%}" if self.long_term_rec else '0%'
        long_score = f"{self.long_term_rec.score:+.2f}" if self.long_term_rec else '0.00'
        long_sl = self.long_term_rec.stop_loss if self.long_term_rec else 0
        long_tp = self.long_term_rec.take_profit if self.long_term_rec else 0
        long_reason = self.long_term_rec.rationale if self.long_term_rec else 'N/A'

        rsi_val = f"{self.indicators.rsi:.2f}" if self.indicators else 'N/A'
        macd_signal = '金叉' if self.indicators and self.indicators.macd > self.indicators.macd_signal else '死叉'
        trend_s = self.indicators.trend_short.upper() if self.indicators else 'N/A'
        trend_l = self.indicators.trend_long.upper() if self.indicators else 'N/A'
        vol_ratio = f"{self.indicators.volume_ratio:.2f}" if self.indicators else 'N/A'
        overall_rating = signal_emoji(tech_summary.get('overall_signal', 'HOLD'))
        key_insight = tech_summary.get('key_observation', 'N/A')
        sentiment_text = sentiment_summary.get('summary_text', 'N/A')

        report = f"""# SLV 白银ETF 分析报告 (简洁版)

**生成时间**: {now.strftime('%Y-%m-%d %H:%M')}

---

## 📊 核心指标

| 指标 | 数值 |
|------|------|
| 当前价格 | ${self.current_price:.2f} |
| 综合评级 | {overall_rating} |
| 市场情绪 | {sentiment_summary.get('overall_sentiment', 'N/A')} ({sentiment_summary.get('sentiment_score', 'N/A')}/100) |

**核心观点**: {key_insight}

**关联市场摘要**: {sentiment_text}

## ⚡ 短期建议 (1-5天)

- **信号**: {short_signal}
- **得分**: {short_score}
- **仓位**: {short_size}
- **止损**: ${short_sl}
- **止盈**: ${short_tp}
- **理由**: {short_reason}

## 📈 长期建议 (1-4周)

- **信号**: {long_signal}
- **得分**: {long_score}
- **仓位**: {long_size}
- **止损**: ${long_sl}
- **止盈**: ${long_tp}
- **理由**: {long_reason}

## 📉 技术指标

- **RSI(14)**: {rsi_val}
- **MACD**: {macd_signal}
- **短期趋势**: {trend_s}
- **长期趋势**: {trend_l}
- **成交量**: {vol_ratio}x 均量

---

**免责声明**: 本报告仅供参考，不构成投资建议。
"""
        return report

    def _generate_full_report(self, analysis_results: Dict) -> str:
        """生成完整版报告"""
        return self._generate_brief_report(analysis_results)

    def run(self, mode: str = "full"):
        """运行完整分析流程"""
        print("=" * 70)
        print("SLV 白银ETF 本地规则分析系统 V3")
        print("=" * 70)
        print(f"📋 报告模式: {'完整版' if mode == 'full' else '简洁版'}")

        # 清理旧报告
        self.cleanup_old_reports(keep_days=3)

        # 1. 实时指标分析（新增）
        self.print_realtime_analysis()

        # 2. 收集行情与关联市场数据
        data = self.collect_data()

        print("\n" + "=" * 70)
        print("✅ 数据收集完成")
        print("=" * 70)

        analysis_results = self.build_analysis_results(data)
        report_path = self.generate_report(analysis_results, mode=mode)

        print("\n" + "=" * 70)
        print("✅ 分析完成！")
        print("=" * 70)
        print(f"\n📄 最终报告: {report_path}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='SLV 白银ETF 本地规则分析系统 V3 - 双维度交易建议',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python slv_analyzer.py                  # 生成完整版报告（默认）
    python slv_analyzer.py --mode full      # 生成完整版报告
    python slv_analyzer.py --mode brief     # 生成简洁版报告
        """
    )

    parser.add_argument(
        '-m', '--mode',
        choices=['full', 'brief'],
        default='full',
        help='报告模式: full=完整版(默认), brief=简洁版'
    )

    args = parser.parse_args()

    analyzer = SLVAnalyzer()
    analyzer.run(mode=args.mode)


if __name__ == "__main__":
    main()

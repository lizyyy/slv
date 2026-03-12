"""
SLV白银ETF量化交易系统 - 配置文件
=====================================
配置文件包含所有系统参数、权重设置和阈值定义

使用说明:
1. 修改API Keys部分，填入你的API密钥
2. 根据需要调整权重和阈值
3. 调整仓位管理参数以匹配你的风险偏好
"""

import os

# ============================================
# API Keys (从环境变量获取，或在此直接设置)
# ============================================
# NewsAPI - 免费版提供100请求/天，用于新闻情绪分析
# 获取地址: https://newsapi.org/
NEWSAPI_KEY = os.getenv('NEWSAPI_KEY', '')

# Finnhub - 免费版提供60请求/分钟，用于新闻和基本面数据
# 获取地址: https://finnhub.io/
FINNHUB_KEY = os.getenv('FINNHUB_KEY', '')

# GNews - 免费版提供100请求/天，新闻数据备选
# 获取地址: https://gnews.io/
GNEWS_KEY = os.getenv('GNEWS_KEY', '')

# Qveris AI - 统一API平台，提供股票/ETF实时价格、夜盘数据等
# 获取地址: https://qveris.ai
QVERIS_API_KEY = os.getenv('QVERIS_API_KEY', 'sk-g8qNOAl5g7URJRToei3zohZ6iWP_JjdHl6USVXWMLcU')

# ============================================
# 基础配置
# ============================================
TICKER = "SLV"  # 白银ETF代码
INTERVAL_MINUTES = 30  # 执行间隔（分钟）
TIMEZONE = "America/New_York"  # 交易时区

# ============================================
# 信号权重配置
# ============================================
SIGNAL_WEIGHTS = {
    "technical": 0.50,  # 技术信号权重 50%
    "sentiment": 0.30,  # 情绪信号权重 30%
    "trend": 0.20,      # 趋势信号权重 20%
}

# 验证权重总和为1
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 0.001, "权重总和必须等于1"

# ============================================
# 信号评分阈值配置
# ============================================
# 各信号类型的评分范围: -1.0 (强烈看跌) ~ +1.0 (强烈看涨)
SIGNAL_THRESHOLDS = {
    "strong_buy": 0.70,      # 强烈买入阈值
    "buy": 0.30,             # 买入阈值
    "hold_upper": 0.10,      # 持有上边界
    "hold_lower": -0.10,     # 持有下边界
    "sell": -0.30,           # 卖出阈值
    "strong_sell": -0.70,    # 强烈卖出阈值
}

# ============================================
# 仓位管理配置
# ============================================
POSITION_SIZING = {
    "strong_buy": 0.80,   # 强烈买入 = 80%仓位
    "buy": 0.50,          # 买入 = 50%仓位
    "hold": 0.0,          # 持有 = 保持当前仓位
    "sell": 0.20,         # 卖出 = 减仓至20%
    "strong_sell": 0.05,  # 强烈卖出 = 减仓至5%
}

# 最大仓位限制
MAX_POSITION_SIZE = 0.90  # 最大90%仓位
MIN_POSITION_SIZE = 0.05  # 最小5%仓位（保留底仓）

# ============================================
# 止损止盈配置 (基于ATR倍数)
# ============================================
RISK_MANAGEMENT = {
    "stop_loss_atr_multiplier": 2.0,      # 止损 = 2倍ATR
    "take_profit_atr_multiplier": 3.0,    # 止盈 = 3倍ATR
    "trailing_stop_atr_multiplier": 1.5,  # 移动止损 = 1.5倍ATR
    "max_risk_per_trade": 0.02,           # 单笔最大风险2%
    "max_daily_loss": 0.05,               # 日最大亏损5%
}

# ============================================
# 复盘系统配置
# ============================================
BACKTEST_CONFIG = {
    "prediction_horizon_minutes": 120,  # 预测验证时间: 2小时
    "min_predictions_for_stats": 10,    # 最小预测样本数
    "accuracy_threshold_good": 0.60,    # 良好准确率阈值
    "accuracy_threshold_excellent": 0.75, # 优秀准确率阈值
}

# ============================================
# 数据存储配置
# ============================================
DATA_PATHS = {
    "predictions": "data/predictions.json",      # 预测记录
    "signals": "data/signals_history.csv",       # 信号历史
    "trades": "data/trade_history.csv",          # 交易记录
    "performance": "data/performance_metrics.json", # 绩效指标
    "logs": "logs/trading_system.log",           # 日志文件
    "cache": "cache/",                           # 缓存目录
}

# ============================================
# 日志配置
# ============================================
LOGGING_CONFIG = {
    "level": "INFO",           # 日志级别
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "max_bytes": 10485760,     # 单个日志文件最大10MB
    "backup_count": 5,         # 保留5个备份文件
}

# ============================================
# 技术指标参数
# ============================================
TECHNICAL_PARAMS = {
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bb_period": 20,
    "bb_std": 2,
    "atr_period": 14,
    "sma_short": 20,
    "sma_long": 50,
    "volume_ma_period": 20,
}

# ============================================
# 情绪分析配置
# ============================================
SENTIMENT_CONFIG = {
    "news_sources": ["bloomberg", "reuters", "cnbc", "marketwatch"],
    "social_sources": ["twitter", "reddit", "stocktwits"],
    "sentiment_refresh_minutes": 30,
    "keywords": ["silver", "SLV", "precious metals", "gold silver ratio"],
    # 情绪权重
    "news_sentiment_weight": 0.35,
    "fear_greed_weight": 0.25,
    "etf_holdings_weight": 0.20,
    "technical_sentiment_weight": 0.20,
}

# ============================================
# 趋势判断配置
# ============================================
TREND_CONFIG = {
    "short_term_period": 5,    # 短期趋势: 5个周期
    "medium_term_period": 10,  # 中期趋势: 10个周期
    "long_term_period": 20,    # 长期趋势: 20个周期
    "trend_strength_threshold": 0.6,  # 趋势强度阈值
}

# ============================================
# 错误处理和重试配置
# ============================================
RETRY_CONFIG = {
    "max_retries": 3,           # 最大重试次数
    "retry_delay_seconds": 5,   # 重试间隔
    "timeout_seconds": 30,      # 请求超时
}

# ============================================
# 通知配置 (可选)
# ============================================
NOTIFICATION_CONFIG = {
    "enable_email": False,
    "enable_sms": False,
    "enable_webhook": False,
    "strong_signal_only": True,  # 仅通知强烈信号
}

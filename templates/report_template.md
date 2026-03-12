# SLV 白银ETF 分析报告

**报告生成时间**: {{report_date}}
**数据截止日期**: {{data_date}}
**分析师**: AI分析系统

---

## 执行摘要

| 指标 | 数值 |
|------|------|
| 当前价格 | ${{current_price}} |
| 日涨跌 | {{price_change}} ({{price_change_pct}}%) |
| 成交量 | {{volume}} |
| 综合评级 | {{overall_rating}} |
| 建议操作 | {{recommended_action}} |

**核心观点**: {{key_insight}}

---

## 一、市场情绪分析

### 1.1 情绪综合评分

```
恐惧 ████████░░░░░░░░░░░░ 贪婪
     {{sentiment_visual_bar}}
     当前得分: {{sentiment_score}}/100 ({{sentiment_category}})
```

### 1.2 各维度分析

#### 恐慌/贪婪指数
- **当前值**: {{fear_greed_value}}
- **状态**: {{fear_greed_status}}
- **趋势**: {{fear_greed_trend}}
- **分析**: {{fear_greed_analysis}}

#### 资金流向
- **5日净流入**: ${{fund_flow_5d}}
- **机构持仓变化**: {{institutional_change}}
- **分析**: {{fund_flow_analysis}}

#### 关联市场情绪
- **美元指数(DXY)**: {{dxy_value}} ({{dxy_impact}})
- **VIX恐慌指数**: {{vix_value}} ({{vix_impact}})
- **黄金走势**: {{gold_correlation}}
- **金银比**: {{gold_silver_ratio}} ({{gsr_assessment}})

#### 量价分析
- **成交量 vs 20日均量**: {{volume_vs_avg}}
- **价格位置(52周)**: {{price_position_52w}}
- **分析**: {{volume_price_analysis}}

### 1.3 情绪分析结论

{{sentiment_summary}}

**风险因素**: {{sentiment_risks}}

---

## 二、技术分析

### 2.1 趋势分析

| 时间框架 | 趋势方向 | 强度 | 描述 |
|----------|----------|------|------|
| 短期(5-10日) | {{short_term_trend}} | {{short_term_strength}} | {{short_term_desc}} |
| 中期(20-30日) | {{medium_term_trend}} | {{medium_term_strength}} | {{medium_term_desc}} |
| 长期(60日+) | {{long_term_trend}} | {{long_term_strength}} | {{long_term_desc}} |

### 2.2 移动平均线

```
价格: {{current_price}}
      |
MA5:  {{ma5_value}}  {{ma5_signal}}
MA10: {{ma10_value}} {{ma10_signal}}
MA20: {{ma20_value}} {{ma20_signal}}
MA60: {{ma60_value}} {{ma60_signal}}
```

**均线排列**: {{ma_alignment}}

### 2.3 支撑与阻力位

```
阻力位 R2: {{r2_level}} ({{r2_strength}})
阻力位 R1: {{r1_level}} ({{r1_strength}})
━━━━━━━━━━━━━━━━━━━━━━
枢轴点:    {{pivot_point}}
━━━━━━━━━━━━━━━━━━━━━━
支撑位 S1: {{s1_level}} ({{s1_strength}})
支撑位 S2: {{s2_level}} ({{s2_strength}})
```

### 2.4 动量指标

#### RSI (14日)
- **数值**: {{rsi_value}}
- **信号**: {{rsi_signal}}
- **解读**: {{rsi_interpretation}}

#### MACD
- **DIF**: {{macd_dif}}
- **DEA**: {{macd_dea}}
- **柱状图**: {{macd_histogram}}
- **信号**: {{macd_signal}}
- **解读**: {{macd_interpretation}}

### 2.5 成交量分析

- **当前成交量**: {{current_volume}}
- **20日均量**: {{avg_volume_20d}}
- **量比**: {{volume_ratio}}
- **信号**: {{volume_signal}}
- **量价配合**: {{volume_price_divergence}}

### 2.6 形态识别

**识别到的形态**:
{{patterns_found}}

**K线信号**:
{{candlestick_signals}}

### 2.7 技术分析结论

{{technical_summary}}

---

## 三、交易建议

### 3.1 综合评级

```
        强烈买入
            ▲
            │ {{strong_buy_indicator}}
    买入    │
            │ {{buy_indicator}}
谨慎买入    │
━━━━━━━━━━━━┼━━━━━━━━━━━━
   观望     │
            │ {{hold_indicator}}
谨慎卖出    │
            │ {{sell_indicator}}
    卖出    │
            │ {{strong_sell_indicator}}
            ▼
        强烈卖出
```

**当前建议**: {{final_recommendation}}

### 3.2 交易参数

| 参数 | 数值 |
|------|------|
| 建议入场价 | ${{entry_price}} |
| 止损位 | ${{stop_loss}} |
| 目标位 | ${{take_profit}} |
| 风险回报比 | {{risk_reward_ratio}}:1 |
| 适合周期 | {{suitable_timeframe}} |
| 风险等级 | {{risk_level}} |

### 3.3 操作建议

{{action_rationale}}

---

## 四、风险提示

### 4.1 主要风险因素

{{risk_factors}}

### 4.2 逆向信号

{{contrarian_signals}}

### 4.3 关键事件提醒

{{upcoming_events}}

---

## 五、数据附录

### 5.1 原始数据

```json
{
  "symbol": "SLV",
  "current_price": {{current_price}},
  "open": {{open_price}},
  "high": {{high_price}},
  "low": {{low_price}},
  "volume": {{volume}},
  "timestamp": "{{timestamp}}"
}
```

### 5.2 数据来源

- 价格数据: NASDAQ API
- 情绪数据: {{sentiment_data_source}}
- 技术指标: 基于OHLC数据计算

---

**免责声明**: 本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。

---

*报告生成时间: {{report_date}} | 版本: {{report_version}}*

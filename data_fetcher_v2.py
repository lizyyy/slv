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
import subprocess
from zoneinfo import ZoneInfo

from requests.exceptions import RequestException, Timeout

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
    YAHOO_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/SLV"
    YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
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
    YAHOO_HEADERS = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh-Hans;q=0.9',
        'Referer': 'https://finance.yahoo.com/quote/SLV/',
        'Origin': 'https://finance.yahoo.com',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15'
    }
    BEIJING_TZ = ZoneInfo("Asia/Shanghai")

    def __init__(self, data_dir: str = "."):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.yahoo_session = requests.Session()
        self.yahoo_session.headers.update(self.YAHOO_HEADERS)
        self.data_dir = Path(data_dir)
        self.historical_file = self.data_dir / "slv_daily_data.csv"
        self.qveris = QverisClient()

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

    def _build_yahoo_endpoint_status(self) -> Dict:
        """单个 Yahoo 接口调用状态"""
        return {
            "status": "not_attempted",
            "failure_reason": None,
            "message": None,
            "http_status": None,
        }

    def _build_yahoo_status(self, preferred_window: bool) -> Dict:
        """Yahoo 抓取总状态"""
        return {
            "preferred_window": preferred_window,
            "attempted": False,
            "available": False,
            "used_for_price": False,
            "source": None,
            "failure_reason": None,
            "message": None,
            "rate_limited": False,
            "timed_out": False,
            "chart": self._build_yahoo_endpoint_status(),
            "quote": self._build_yahoo_endpoint_status(),
        }

    def _set_endpoint_failure(
        self,
        endpoint_status: Dict,
        reason: str,
        message: str,
        http_status: Optional[int] = None
    ) -> None:
        """记录单个 Yahoo 接口失败详情"""
        endpoint_status["status"] = "failed"
        endpoint_status["failure_reason"] = reason
        endpoint_status["message"] = message
        endpoint_status["http_status"] = http_status

    def _sync_yahoo_status_flags(self, yahoo_status: Dict) -> None:
        """汇总各 Yahoo 接口状态"""
        endpoints = [yahoo_status["chart"], yahoo_status["quote"]]
        yahoo_status["rate_limited"] = any(
            item.get("failure_reason") == "rate_limited" for item in endpoints
        )
        yahoo_status["timed_out"] = any(
            item.get("failure_reason") == "timeout" for item in endpoints
        )

    def _request_yahoo_json(
        self,
        url: str,
        params: Dict,
        endpoint_name: str,
        timeout: int = 8
    ) -> Tuple[Optional[Dict], Dict]:
        """统一处理 Yahoo JSON 请求及错误分类"""
        endpoint_status = self._build_yahoo_endpoint_status()
        endpoint_status["status"] = "attempted"

        curl_data, curl_status = self._request_yahoo_json_via_curl(url, params, endpoint_name, timeout)
        if curl_status["status"] == "success":
            return curl_data, curl_status

        # curl 已经明确返回限频/超时/鉴权错误时，不再重复请求
        if curl_status.get("failure_reason") in {"rate_limited", "timeout", "unauthorized"}:
            return None, curl_status

        try:
            response = self.yahoo_session.get(url, params=params, timeout=timeout)
            endpoint_status["http_status"] = response.status_code
            response_text = response.text[:300]

            if response.status_code == 429 or "Too Many Requests" in response_text:
                self._set_endpoint_failure(
                    endpoint_status,
                    "rate_limited",
                    f"Yahoo {endpoint_name} 接口频次受限",
                    response.status_code
                )
                return None, endpoint_status

            if response.status_code in (401, 403):
                self._set_endpoint_failure(
                    endpoint_status,
                    "unauthorized",
                    f"Yahoo {endpoint_name} 接口未授权: HTTP {response.status_code}",
                    response.status_code
                )
                return None, endpoint_status

            response.raise_for_status()
            data = response.json()
            endpoint_status["status"] = "success"
            return data, endpoint_status
        except Timeout:
            self._set_endpoint_failure(
                endpoint_status,
                "timeout",
                f"Yahoo {endpoint_name} 接口请求超时"
            )
        except ValueError as exc:
            self._set_endpoint_failure(
                endpoint_status,
                "invalid_response",
                f"Yahoo {endpoint_name} 返回了无法解析的内容: {exc}"
            )
        except RequestException as exc:
            reason = "rate_limited" if "Too Many Requests" in str(exc) else "request_failed"
            self._set_endpoint_failure(
                endpoint_status,
                reason,
                f"Yahoo {endpoint_name} 请求失败: {exc}"
            )
        except Exception as exc:
            self._set_endpoint_failure(
                endpoint_status,
                "unexpected_error",
                f"Yahoo {endpoint_name} 未知错误: {exc}"
            )

        return None, endpoint_status

    def _request_yahoo_json_via_curl(
        self,
        url: str,
        params: Dict,
        endpoint_name: str,
        timeout: int = 8
    ) -> Tuple[Optional[Dict], Dict]:
        """优先使用 curl 访问 Yahoo，规避 requests 在部分环境下的反爬拦截"""
        endpoint_status = self._build_yahoo_endpoint_status()
        endpoint_status["status"] = "attempted"

        try:
            prepared_url = requests.Request("GET", url, params=params).prepare().url
            curl_cmd = [
                "curl",
                "-sS",
                "-L",
                "--compressed",
                "--connect-timeout",
                str(min(timeout, 5)),
                "--max-time",
                str(timeout),
                "-H",
                "Accept: application/json, text/plain, */*",
                "-H",
                "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
                "-H",
                "Referer: https://finance.yahoo.com/quote/SLV/",
                "-w",
                "\n__CURL_STATUS__:%{http_code}",
                prepared_url,
            ]
            result = subprocess.run(curl_cmd, capture_output=True, text=True, check=False)

            if result.returncode == 28:
                self._set_endpoint_failure(
                    endpoint_status,
                    "timeout",
                    f"Yahoo {endpoint_name} 接口请求超时(curl)"
                )
                return None, endpoint_status

            if result.returncode != 0:
                self._set_endpoint_failure(
                    endpoint_status,
                    "request_failed",
                    f"Yahoo {endpoint_name} curl 请求失败: {result.stderr.strip() or result.returncode}"
                )
                return None, endpoint_status

            output = result.stdout or ""
            marker = "\n__CURL_STATUS__:"
            if marker not in output:
                self._set_endpoint_failure(
                    endpoint_status,
                    "invalid_response",
                    f"Yahoo {endpoint_name} curl 响应缺少状态码标记"
                )
                return None, endpoint_status

            body, status_code_text = output.rsplit(marker, 1)
            status_code = int(status_code_text.strip() or 0)
            endpoint_status["http_status"] = status_code
            response_text = body[:300]

            if status_code == 429 or "Too Many Requests" in response_text:
                self._set_endpoint_failure(
                    endpoint_status,
                    "rate_limited",
                    f"Yahoo {endpoint_name} 接口频次受限",
                    status_code
                )
                return None, endpoint_status

            if status_code in (401, 403):
                self._set_endpoint_failure(
                    endpoint_status,
                    "unauthorized",
                    f"Yahoo {endpoint_name} 接口未授权: HTTP {status_code}",
                    status_code
                )
                return None, endpoint_status

            if status_code >= 400:
                self._set_endpoint_failure(
                    endpoint_status,
                    "request_failed",
                    f"Yahoo {endpoint_name} 接口返回 HTTP {status_code}",
                    status_code
                )
                return None, endpoint_status

            try:
                data = json.loads(body)
            except ValueError as exc:
                self._set_endpoint_failure(
                    endpoint_status,
                    "invalid_response",
                    f"Yahoo {endpoint_name} curl 返回了无法解析的内容: {exc}",
                    status_code
                )
                return None, endpoint_status

            endpoint_status["status"] = "success"
            return data, endpoint_status
        except FileNotFoundError:
            self._set_endpoint_failure(
                endpoint_status,
                "request_failed",
                "系统未找到 curl，退回 requests"
            )
        except Exception as exc:
            self._set_endpoint_failure(
                endpoint_status,
                "unexpected_error",
                f"Yahoo {endpoint_name} curl 未知错误: {exc}"
            )

        return None, endpoint_status

    def _to_float(self, value) -> Optional[float]:
        """尽量转成浮点数"""
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _series_value(self, series: Optional[List], idx: int) -> Optional[float]:
        """安全读取行情序列中的指定位置"""
        if series is None or idx >= len(series):
            return None
        return self._to_float(series[idx])

    def _is_yahoo_priority_window(self) -> bool:
        """北京时间 08:00-16:00 优先使用 Yahoo 夜盘价格"""
        now_bj = datetime.now(self.BEIJING_TZ)
        return 8 <= now_bj.hour < 16

    def _classify_yahoo_period(self, timestamp: int, meta: Dict) -> str:
        """根据 Yahoo 返回的交易时段定义判断价格属于盘前/盘中/盘后"""
        periods = meta.get("currentTradingPeriod", {})

        for period_name in ("pre", "regular", "post"):
            period = periods.get(period_name) or {}
            start = period.get("start")
            end = period.get("end")
            if start is None or end is None:
                continue
            if start <= timestamp < end:
                return period_name

        post_period = periods.get("post") or {}
        if post_period.get("end") == timestamp:
            return "post"
        return "unknown"

    def _parse_yahoo_chart_quote(self, data: Dict) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        """解析 Yahoo 分钟级图表接口，优先提取夜盘价格"""
        chart = data.get("chart", {})
        if chart.get("error"):
            error = chart["error"]
            return None, "api_error", error.get("description") or str(error)

        results = chart.get("result") or []
        if not results:
            return None, "empty_data", "Yahoo chart 接口没有返回 result"

        result = results[0]
        meta = result.get("meta") or {}
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators", {}).get("quote") or []

        if not timestamps or not indicators:
            return None, "empty_data", "Yahoo chart 接口没有返回有效分钟数据"

        quote_data = indicators[0]
        rows = []
        for idx, ts in enumerate(timestamps):
            close = self._series_value(quote_data.get("close"), idx)
            if close is None:
                continue

            rows.append({
                "timestamp": int(ts),
                "period": self._classify_yahoo_period(int(ts), meta),
                "open": self._series_value(quote_data.get("open"), idx),
                "high": self._series_value(quote_data.get("high"), idx),
                "low": self._series_value(quote_data.get("low"), idx),
                "close": close,
                "volume": self._series_value(quote_data.get("volume"), idx),
            })

        if not rows:
            return None, "empty_data", "Yahoo chart 分钟数据全部为空"

        latest = rows[-1]
        pre_rows = [row for row in rows if row["period"] == "pre"]
        post_rows = [row for row in rows if row["period"] == "post"]
        extended_rows = pre_rows + post_rows

        pre_market_price = pre_rows[-1]["close"] if pre_rows else None
        post_market_price = post_rows[-1]["close"] if post_rows else None

        def _best_price(row: Dict, field: str) -> Optional[float]:
            return row.get(field) if row.get(field) is not None else row.get("close")

        extended_high = max(
            (_best_price(row, "high") for row in extended_rows),
            default=None
        )
        extended_low = min(
            (_best_price(row, "low") for row in extended_rows),
            default=None
        )

        previous_close = self._to_float(meta.get("previousClose") or meta.get("chartPreviousClose"))
        current_price = latest["close"]
        net_change = current_price - previous_close if current_price is not None and previous_close is not None else None
        change_pct = ((net_change / previous_close) * 100) if net_change is not None and previous_close else None

        latest_dt = datetime.fromtimestamp(latest["timestamp"], tz=timezone.utc).astimezone(self.BEIJING_TZ)
        is_night_session = latest["period"] in {"pre", "post"}

        return {
            "symbol": "SLV",
            "name": meta.get("longName") or meta.get("shortName") or "iShares Silver Trust",
            "last_price": current_price,
            "net_change": net_change,
            "change_pct": change_pct,
            "volume": int(latest["volume"]) if latest["volume"] is not None else None,
            "bid": None,
            "ask": None,
            "open": latest.get("open"),
            "high": latest.get("high"),
            "low": latest.get("low"),
            "previous_close": previous_close,
            "timestamp": latest_dt.isoformat(),
            "is_realtime": True,
            "price_source": "yahoo_chart_night" if is_night_session else "yahoo_chart",
            "market_status": "extended_hours" if is_night_session else "regular_hours",
            "is_night_session": is_night_session,
            "yahoo_price_period": latest["period"],
            "pre_market_price": pre_market_price,
            "post_market_price": post_market_price,
            "regular_price": self._to_float(meta.get("regularMarketPrice")),
            "extended_hours_high": extended_high,
            "extended_hours_low": extended_low,
            "yahoo_latest_timestamp": latest_dt.isoformat(),
            "yahoo_latest_timestamp_epoch": latest["timestamp"],
            "yahoo_exchange_timezone": meta.get("exchangeTimezoneName"),
        }, None, None

    def _parse_yahoo_quote_api(self, data: Dict) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        """解析 Yahoo 报价接口，作为分钟图失败后的回退"""
        finance = data.get("finance", {})
        api_error = finance.get("error")
        if api_error:
            code = (api_error.get("code") or "").lower()
            reason = "unauthorized" if code == "unauthorized" else "api_error"
            return None, reason, api_error.get("description") or str(api_error)

        results = finance.get("result") or []
        if not results:
            return None, "empty_data", "Yahoo quote 接口没有返回 result"

        quote = results[0]
        post_market_price = self._to_float(quote.get("postMarketPrice"))
        pre_market_price = self._to_float(quote.get("preMarketPrice"))
        regular_price = self._to_float(quote.get("regularMarketPrice"))

        selected_price = post_market_price or pre_market_price or regular_price
        if selected_price is None:
            return None, "empty_data", "Yahoo quote 接口没有可用价格字段"

        if post_market_price is not None:
            price_period = "post"
            timestamp = quote.get("postMarketTime") or quote.get("regularMarketTime")
        elif pre_market_price is not None:
            price_period = "pre"
            timestamp = quote.get("preMarketTime") or quote.get("regularMarketTime")
        else:
            price_period = "regular"
            timestamp = quote.get("regularMarketTime")

        previous_close = self._to_float(quote.get("regularMarketPreviousClose"))
        net_change = selected_price - previous_close if previous_close is not None else self._to_float(quote.get("regularMarketChange"))
        change_pct = (
            (net_change / previous_close) * 100
            if net_change is not None and previous_close
            else self._to_float(quote.get("regularMarketChangePercent"))
        )

        timestamp_iso = None
        if timestamp:
            timestamp_iso = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).astimezone(self.BEIJING_TZ).isoformat()

        is_night_session = price_period in {"pre", "post"}

        return {
            "symbol": quote.get("symbol", "SLV"),
            "name": quote.get("longName") or quote.get("shortName") or "iShares Silver Trust",
            "last_price": selected_price,
            "net_change": net_change,
            "change_pct": change_pct,
            "volume": int(quote.get("regularMarketVolume")) if quote.get("regularMarketVolume") is not None else None,
            "bid": self._to_float(quote.get("bid")),
            "ask": self._to_float(quote.get("ask")),
            "previous_close": previous_close,
            "timestamp": timestamp_iso,
            "is_realtime": True,
            "price_source": "yahoo_quote_night" if is_night_session else "yahoo_quote",
            "market_status": "extended_hours" if is_night_session else "regular_hours",
            "is_night_session": is_night_session,
            "yahoo_price_period": price_period,
            "pre_market_price": pre_market_price,
            "post_market_price": post_market_price,
            "regular_price": regular_price,
            "extended_hours_high": None,
            "extended_hours_low": None,
        }, None, None

    def get_yahoo_realtime_data(self, preferred_window: bool = False) -> Tuple[Optional[Dict], Dict]:
        """
        通过 Yahoo 直连接口获取实时/夜盘价格。
        优先使用分钟级图表接口，报价接口作为回退。
        """
        yahoo_status = self._build_yahoo_status(preferred_window)
        yahoo_status["attempted"] = True

        chart_data, chart_status = self._request_yahoo_json(
            self.YAHOO_CHART_URL,
            {"interval": "1m", "range": "1d", "includePrePost": "true"},
            "chart"
        )
        yahoo_status["chart"] = chart_status

        if chart_data is not None:
            yahoo_quote, reason, message = self._parse_yahoo_chart_quote(chart_data)
            if yahoo_quote:
                yahoo_status["available"] = True
                yahoo_status["source"] = "chart"
                self._sync_yahoo_status_flags(yahoo_status)
                return yahoo_quote, yahoo_status
            self._set_endpoint_failure(yahoo_status["chart"], reason or "invalid_response", message or "Yahoo chart 解析失败")

        quote_data, quote_status = self._request_yahoo_json(
            self.YAHOO_QUOTE_URL,
            {"symbols": "SLV"},
            "quote"
        )
        yahoo_status["quote"] = quote_status

        if quote_data is not None:
            yahoo_quote, reason, message = self._parse_yahoo_quote_api(quote_data)
            if yahoo_quote:
                yahoo_status["available"] = True
                yahoo_status["source"] = "quote"
                self._sync_yahoo_status_flags(yahoo_status)
                return yahoo_quote, yahoo_status
            self._set_endpoint_failure(yahoo_status["quote"], reason or "invalid_response", message or "Yahoo quote 解析失败")

        if not yahoo_status["failure_reason"]:
            for endpoint_name in ("chart", "quote"):
                endpoint = yahoo_status[endpoint_name]
                if endpoint.get("failure_reason"):
                    yahoo_status["failure_reason"] = endpoint["failure_reason"]
                    yahoo_status["message"] = endpoint.get("message")
                    break

        self._sync_yahoo_status_flags(yahoo_status)
        return None, yahoo_status

    def get_yfinance_data(self) -> Optional[Dict]:
        """
        向后兼容旧方法名。
        实际上改为使用 Yahoo 直连接口返回夜盘/延长交易信息。
        """
        yahoo_quote, yahoo_status = self.get_yahoo_realtime_data(
            preferred_window=self._is_yahoo_priority_window()
        )
        if not yahoo_quote:
            logger.warning(
                "Yahoo Finance data unavailable: %s",
                yahoo_status.get("message") or yahoo_status.get("failure_reason")
            )
            return None

        return {
            "post_market_price": yahoo_quote.get("post_market_price"),
            "pre_market_price": yahoo_quote.get("pre_market_price"),
            "regular_price": yahoo_quote.get("regular_price"),
            "previous_close": yahoo_quote.get("previous_close"),
            "extended_hours_high": yahoo_quote.get("extended_hours_high"),
            "extended_hours_low": yahoo_quote.get("extended_hours_low"),
            "data_source": yahoo_quote.get("price_source"),
            "is_extended_hours": yahoo_quote.get("is_night_session", False),
            "yahoo_status": yahoo_status,
        }

    def _merge_yahoo_context(self, quote: Dict, yahoo_quote: Dict) -> Dict:
        """把 Yahoo 的夜盘补充信息合并到其他数据源报价中"""
        merged = dict(quote)

        for field in (
            "pre_market_price",
            "post_market_price",
            "extended_hours_high",
            "extended_hours_low",
            "regular_price",
            "yahoo_price_period",
            "yahoo_latest_timestamp",
            "yahoo_latest_timestamp_epoch",
            "yahoo_exchange_timezone",
        ):
            if yahoo_quote.get(field) is not None:
                merged[field] = yahoo_quote.get(field)

        if yahoo_quote.get("is_night_session") and merged.get("volume") in (None, 0):
            merged["last_price"] = yahoo_quote.get("last_price") or merged.get("last_price")
            merged["net_change"] = yahoo_quote.get("net_change")
            merged["change_pct"] = yahoo_quote.get("change_pct")
            merged["timestamp"] = yahoo_quote.get("timestamp") or merged.get("timestamp")
            merged["price_source"] = yahoo_quote.get("price_source") or merged.get("price_source")
            merged["market_status"] = yahoo_quote.get("market_status") or merged.get("market_status")
            merged["is_night_session"] = True
            if yahoo_quote.get("previous_close") is not None:
                merged["previous_close"] = yahoo_quote.get("previous_close")
            if yahoo_quote.get("volume") is not None:
                merged["volume"] = yahoo_quote.get("volume")
        else:
            merged.setdefault("is_night_session", False)

        return merged

    def _attach_yahoo_status(self, quote: Optional[Dict], yahoo_status: Dict) -> Optional[Dict]:
        """把 Yahoo 获取状态统一挂到最终报价上"""
        if quote is None:
            return None

        enriched = dict(quote)
        enriched["is_night_session"] = bool(enriched.get("is_night_session"))
        enriched["yahoo_preferred_window"] = yahoo_status.get("preferred_window", False)
        enriched["yahoo_attempted"] = yahoo_status.get("attempted", False)
        enriched["yahoo_available"] = yahoo_status.get("available", False)
        enriched["yahoo_used_for_price"] = yahoo_status.get("used_for_price", False)
        enriched["yahoo_source"] = yahoo_status.get("source")
        enriched["yahoo_failure_reason"] = yahoo_status.get("failure_reason")
        enriched["yahoo_failure_message"] = yahoo_status.get("message")
        enriched["yahoo_rate_limited"] = yahoo_status.get("rate_limited", False)
        enriched["yahoo_timed_out"] = yahoo_status.get("timed_out", False)
        enriched["yahoo_status"] = yahoo_status
        return enriched

    def get_current_quote(self) -> Optional[Dict]:
        """
        获取实时报价
        数据源优先级：
        1. 北京时间 08:00-16:00: 优先 Yahoo 分钟级夜盘价格
        2. 其他时间: NASDAQ API（盘前/盘中/盘后实时价格）- 主要来源
        3. Yahoo Finance（夜盘价格）- 直接获取，补充或回退
        3. Qveris（最后备用）- 当以上都失败时使用
        """
        quote = None
        prefer_yahoo = self._is_yahoo_priority_window()
        yahoo_quote = None
        yahoo_status = self._build_yahoo_status(prefer_yahoo)

        if prefer_yahoo:
            logger.info("北京时间 08:00-16:00，优先尝试 Yahoo 夜盘价格...")
            yahoo_quote, yahoo_status = self.get_yahoo_realtime_data(preferred_window=True)

            if yahoo_quote and yahoo_quote.get("last_price"):
                yahoo_status["used_for_price"] = True
                quote = yahoo_quote
                logger.info(f"Yahoo success: ${quote['last_price']}")
            else:
                logger.warning(
                    "Yahoo unavailable in preferred window, fallback to NASDAQ: %s",
                    yahoo_status.get("message") or yahoo_status.get("failure_reason")
                )

        if not quote:
            logger.info("Trying NASDAQ API...")
            quote = self._get_nasdaq_quote()

            if quote:
                logger.info(f"NASDAQ success: ${quote['last_price']}")

                if not prefer_yahoo:
                    logger.info("Fetching Yahoo Finance extended hours data...")
                    yahoo_quote, yahoo_status = self.get_yahoo_realtime_data(preferred_window=False)
                    if yahoo_quote:
                        quote = self._merge_yahoo_context(quote, yahoo_quote)
                        logger.info(
                            "Yahoo Finance extended hours: pre=$%s, post=$%s",
                            yahoo_quote.get("pre_market_price"),
                            yahoo_quote.get("post_market_price")
                        )
            else:
                logger.warning("NASDAQ API failed, trying Yahoo Finance...")

                if not yahoo_quote:
                    yahoo_quote, yahoo_status = self.get_yahoo_realtime_data(preferred_window=prefer_yahoo)

                if yahoo_quote and yahoo_quote.get("last_price"):
                    yahoo_status["used_for_price"] = True
                    quote = yahoo_quote
                    logger.info(f"Using Yahoo Finance: ${quote['last_price']}")

        # 3. 最后备用：Qveris
        if not quote:
            logger.warning("All primary sources failed, trying Qveris as fallback...")
            qveris_data = self.qveris.get_quote("SLV")
            if qveris_data and qveris_data.get('last_price'):
                quote = qveris_data
                logger.info(f"Using Qveris fallback: ${quote['last_price']}")

        if not quote:
            logger.error("All data sources failed!")
            return None

        return self._attach_yahoo_status(quote, yahoo_status)

    def _get_nasdaq_quote(self) -> Optional[Dict]:
        """从 NASDAQ API 获取实时报价"""
        url = f"{self.BASE_URL}/info"
        params = {'assetclass': 'etf'}

        try:
            response = self.session.get(url, params=params, timeout=30)
            data = response.json()

            if data.get('data') and data['data'].get('primaryData'):
                primary = data['data']['primaryData']
                last_price = self._parse_price(primary.get('lastSalePrice'))
                net_change = self._parse_price(primary.get('netChange'))
                previous_close = (last_price - net_change) if last_price is not None and net_change is not None else None
                return {
                    'symbol': 'SLV',
                    'name': data['data'].get('companyName', 'iShares Silver Trust'),
                    'last_price': last_price,
                    'net_change': net_change,
                    'change_pct': self._parse_pct(primary.get('percentageChange')),
                    'volume': int(primary.get('volume', '0').replace(',', '')) if primary.get('volume') else None,
                    'bid': self._parse_price(primary.get('bidPrice')),
                    'ask': self._parse_price(primary.get('askPrice')),
                    'previous_close': previous_close,
                    'timestamp': primary.get('lastTradeTimestamp'),
                    'is_realtime': primary.get('isRealTime', False),
                    'price_source': 'nasdaq',
                    'market_status': 'regular_hours',
                    'is_night_session': False
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
        current_volume = quote.get('volume') if quote.get('volume') is not None else latest.get('volume', 0)
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

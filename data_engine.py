"""
╔══════════════════════════════════════════════════════════════╗
║            Alpaca Data Engine - Real-time Market Data        ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from collections import defaultdict

import alpaca_trade_api as tradeapi
from alpaca_trade_api.stream import Stream

from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY, BASE_URL,
    DATA_URL, PAPER_TRADING, TRADING
)

logger = logging.getLogger("DataEngine")


class AlpacaDataEngine:
    """
    ═══════════════════════════════════════════════════════
    Data Engine - High Speed & Accuracy
    ═══════════════════════════════════════════════════════
    """

    def __init__(self):
        self.api = tradeapi.REST(
            key_id=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
            base_url=BASE_URL,
            api_version='v2'
        )
        
        # Smart Price Cache
        self._price_cache: Dict[str, dict] = {}
        self._cache_ttl: float = 0.5  # Cache TTL: 0.5s

        # Bars Cache (30s TTL)
        self._bars_cache: Dict[str, dict] = {}
        self._bars_cache_ttl: float = 30.0

        # Market Status Cache (60s TTL)
        self._market_cache: dict = {}
        
        # بيانات البث المباشر
        self._live_quotes: Dict[str, dict] = {}
        self._live_trades: Dict[str, dict] = {}
        self._live_bars: Dict[str, list] = defaultdict(list)
        
        # callbacks
        self._on_quote_callbacks: List[Callable] = []
        self._on_trade_callbacks: List[Callable] = []
        self._on_bar_callbacks: List[Callable] = []
        
        # حالة الاتصال
        self._stream: Optional[Stream] = None
        self._streaming = False
        
        logger.info("📡 محرك البيانات جاهز")

    # ══════════════════════════════════════════════════════
    # 1. بيانات الحساب
    # ══════════════════════════════════════════════════════

    def get_account(self) -> dict:
        """جلب بيانات الحساب"""
        try:
            account = self.api.get_account()
            return {
                "id": account.id,
                "status": account.status,
                "equity": float(account.equity),
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "portfolio_value": float(account.portfolio_value),
                "pattern_day_trader": account.pattern_day_trader,
                "trading_blocked": account.trading_blocked,
                "day_trade_count": int(account.daytrade_count),
                "last_equity": float(account.last_equity),
            }
        except Exception as e:
            logger.error(f"❌ خطأ في جلب بيانات الحساب: {e}")
            return {}

    def get_positions(self) -> List[dict]:
        """جلب جميع المراكز المفتوحة"""
        try:
            positions = self.api.list_positions()
            return [{
                "symbol": p.symbol,
                "quantity": int(p.qty),
                "side": p.side,
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "change_today": float(p.change_today),
            } for p in positions]
        except Exception as e:
            logger.error(f"❌ خطأ في جلب المراكز: {e}")
            return []

    # ══════════════════════════════════════════════════════
    # 2. أسعار فورية (REST API)
    # ══════════════════════════════════════════════════════

    def get_latest_quote(self, symbol: str) -> dict:
        """جلب آخر سعر بأقصى سرعة مع كاش ذكي"""
        # فحص الكاش أولاً
        cached = self._price_cache.get(symbol)
        if cached and (time.time() - cached["timestamp"]) < self._cache_ttl:
            return cached["data"]
        
        try:
            quote = self.api.get_latest_quote(symbol, feed='iex')
            data = {
                "symbol": symbol,
                "bid": float(quote.bp) if hasattr(quote, 'bp') else 0,
                "ask": float(quote.ap) if hasattr(quote, 'ap') else 0,
                "bid_size": int(quote.bs) if hasattr(quote, 'bs') else 0,
                "ask_size": int(quote.as_) if hasattr(quote, 'as_') else 0,
                "mid": 0,
                "spread": 0,
                "spread_pct": 0,
                "timestamp": datetime.now().isoformat()
            }
            
            if data["bid"] > 0 and data["ask"] > 0:
                data["mid"] = (data["bid"] + data["ask"]) / 2
                data["spread"] = data["ask"] - data["bid"]
                data["spread_pct"] = (data["spread"] / data["mid"]) * 100
            
            # تحديث الكاش
            self._price_cache[symbol] = {
                "data": data,
                "timestamp": time.time()
            }
            
            return data
        except Exception as e:
            logger.error(f"❌ خطأ في جلب سعر {symbol}: {e}")
            # حاول من الكاش القديم
            if cached:
                return cached["data"]
            return {"symbol": symbol, "bid": 0, "ask": 0, "mid": 0}

    def get_latest_trade(self, symbol: str) -> dict:
        """جلب آخر صفقة منفذة"""
        try:
            trade = self.api.get_latest_trade(symbol, feed='iex')
            return {
                "symbol": symbol,
                "price": float(trade.p) if hasattr(trade, 'p') else float(trade.price),
                "size": int(trade.s) if hasattr(trade, 's') else int(trade.size),
                "timestamp": str(trade.t) if hasattr(trade, 't') else str(trade.timestamp),
            }
        except Exception as e:
            logger.error(f"❌ خطأ في جلب آخر صفقة {symbol}: {e}")
            return {"symbol": symbol, "price": 0, "size": 0}

    def get_snapshot(self, symbol: str) -> dict:
        """جلب لقطة شاملة للسهم"""
        try:
            snapshot = self.api.get_snapshot(symbol, feed='iex')
            result = {
                "symbol": symbol,
                "latest_trade": {
                    "price": float(snapshot.latest_trade.p) if snapshot.latest_trade else 0,
                    "size": int(snapshot.latest_trade.s) if snapshot.latest_trade else 0,
                },
                "latest_quote": {
                    "bid": float(snapshot.latest_quote.bp) if snapshot.latest_quote else 0,
                    "ask": float(snapshot.latest_quote.ap) if snapshot.latest_quote else 0,
                },
                "minute_bar": {},
                "daily_bar": {},
                "prev_daily_bar": {},
            }
            
            if snapshot.minute_bar:
                result["minute_bar"] = {
                    "open": float(snapshot.minute_bar.o),
                    "high": float(snapshot.minute_bar.h),
                    "low": float(snapshot.minute_bar.l),
                    "close": float(snapshot.minute_bar.c),
                    "volume": int(snapshot.minute_bar.v),
                }
            
            if snapshot.daily_bar:
                result["daily_bar"] = {
                    "open": float(snapshot.daily_bar.o),
                    "high": float(snapshot.daily_bar.h),
                    "low": float(snapshot.daily_bar.l),
                    "close": float(snapshot.daily_bar.c),
                    "volume": int(snapshot.daily_bar.v),
                }
            
            if snapshot.prev_daily_bar:
                result["prev_daily_bar"] = {
                    "open": float(snapshot.prev_daily_bar.o),
                    "high": float(snapshot.prev_daily_bar.h),
                    "low": float(snapshot.prev_daily_bar.l),
                    "close": float(snapshot.prev_daily_bar.c),
                    "volume": int(snapshot.prev_daily_bar.v),
                }
            
            return result
        except Exception as e:
            logger.error(f"❌ خطأ في جلب لقطة {symbol}: {e}")
            return {"symbol": symbol}

    def get_multi_quotes(self, symbols: List[str]) -> Dict[str, dict]:
        """جلب أسعار عدة أسهم دفعة واحدة (أسرع) - مع إعادة محاولة ذكية"""
        results = {}
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                quotes = self.api.get_latest_quotes(symbols, feed='iex')
                for symbol, quote in quotes.items():
                    bid = float(quote.bp) if hasattr(quote, 'bp') else 0
                    ask = float(quote.ap) if hasattr(quote, 'ap') else 0
                    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
                    
                    results[symbol] = {
                        "symbol": symbol,
                        "bid": bid,
                        "ask": ask,
                        "mid": mid,
                        "spread": ask - bid if bid > 0 else 0,
                        "spread_pct": ((ask - bid) / mid * 100) if mid > 0 else 0,
                    }
                    
                    # تحديث الكاش
                    self._price_cache[symbol] = {
                        "data": results[symbol],
                        "timestamp": time.time()
                    }
                return results # Success!
            except Exception as e:
                logger.warning(f"⚠️ محاولة {attempt + 1}/{max_retries} - فشل جلب الأسعار، جاري إعادة المحاولة... {str(e).splitlines()[0][:100]}")
                time.sleep(0.5)
                
        logger.error(f"❌ خطأ نهائي في جلب أسعار متعددة بعد {max_retries} محاولات")
        return results

    # ══════════════════════════════════════════════════════
    # 3. بيانات تاريخية
    # ══════════════════════════════════════════════════════

    def get_bars(self, symbol: str, timeframe: str = "1Min",
                 limit: int = 100) -> List[dict]:
        """
        جلب بيانات الشموع التاريخية
        timeframe: 1Min, 5Min, 15Min, 1Hour, 1Day
        """
        # فحص كاش الشموع
        cache_key = f"{symbol}_{timeframe}_{limit}"
        cached = self._bars_cache.get(cache_key)
        if cached and (time.time() - cached["timestamp"]) < self._bars_cache_ttl:
            return cached["data"]

        try:
            end = datetime.now()
            if timeframe in ("1Min", "5Min", "15Min"):
                start = end - timedelta(days=5)
            elif timeframe == "1Hour":
                start = end - timedelta(days=30)
            else:
                start = end - timedelta(days=365)
            
            bars = self.api.get_bars(
                symbol,
                timeframe,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                limit=limit,
                adjustment='raw',
                feed='iex'
            )
            
            result = []
            for bar in bars:
                result.append({
                    "timestamp": str(bar.t),
                    "open": float(bar.o),
                    "high": float(bar.h),
                    "low": float(bar.l),
                    "close": float(bar.c),
                    "volume": int(bar.v),
                    "vwap": float(bar.vw) if hasattr(bar, 'vw') else 0,
                })

            # حفظ في الكاش
            self._bars_cache[cache_key] = {"data": result, "timestamp": time.time()}
            return result
        except Exception as e:
            logger.error(f"❌ خطأ في جلب شموع {symbol}: {e}")
            # إرجاع كاش قديم عند الخطأ
            if cached:
                return cached["data"]
            return []

    def get_daily_bars(self, symbol: str, days: int = 250) -> List[dict]:
        """
        جلب شموع يومية - مُحسَّنة للاستراتيجية الأسبوعية.
        TTL = 4 ساعات لأن الشموع اليومية لا تتغير كثيراً.
        """
        cache_key = f"{symbol}_1Day_{days}"
        cached = self._bars_cache.get(cache_key)
        # TTL 4 ساعات للشموع اليومية
        if cached and (time.time() - cached["timestamp"]) < 14400:
            return cached["data"]
        try:
            end   = datetime.now()
            start = end - timedelta(days=days + 30)   # هامش إضافي لتجاوز عطلات
            bars  = self.api.get_bars(
                symbol, "1Day",
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                limit=days,
                adjustment='raw',
                feed='iex'
            )
            result = []
            for bar in bars:
                result.append({
                    "timestamp": str(bar.t),
                    "open":   float(bar.o),
                    "high":   float(bar.h),
                    "low":    float(bar.l),
                    "close":  float(bar.c),
                    "volume": int(bar.v),
                    "vwap":   float(bar.vw) if hasattr(bar, 'vw') else 0,
                    "symbol": symbol,
                })
            self._bars_cache[cache_key] = {"data": result, "timestamp": time.time()}
            logger.info(f"📅 {symbol}: {len(result)} شمعة يومية")
            return result
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الشموع اليومية لـ {symbol}: {e}")
            if cached:
                return cached["data"]
            return []

    def get_intraday_bars(self, symbol: str, minutes: int = 1,
                          limit: int = 100) -> List[dict]:
        """جلب شموع خلال اليوم"""
        tf = f"{minutes}Min"
        return self.get_bars(symbol, tf, limit=limit)

    # ══════════════════════════════════════════════════════
    # 4. بث مباشر (WebSocket)
    # ══════════════════════════════════════════════════════

    async def start_streaming(self, symbols: List[str]):
        """بدء بث البيانات المباشر"""
        try:
            self._stream = Stream(
                ALPACA_API_KEY,
                ALPACA_SECRET_KEY,
                base_url=BASE_URL,
                data_feed='iex'
            )
            
            # الاشتراك في الأسعار
            @self._stream.on_quote(*symbols)
            async def on_quote(quote):
                data = {
                    "symbol": quote.symbol,
                    "bid": float(quote.bp),
                    "ask": float(quote.ap),
                    "bid_size": int(quote.bs),
                    "ask_size": int(quote.as_),
                    "timestamp": str(quote.t),
                }
                data["mid"] = (data["bid"] + data["ask"]) / 2
                data["spread"] = data["ask"] - data["bid"]
                
                self._live_quotes[quote.symbol] = data
                self._price_cache[quote.symbol] = {
                    "data": data,
                    "timestamp": time.time()
                }
                
                for callback in self._on_quote_callbacks:
                    await callback(data) if asyncio.iscoroutinefunction(callback) \
                        else callback(data)

            # الاشتراك في الصفقات
            @self._stream.on_trade(*symbols)
            async def on_trade(trade):
                data = {
                    "symbol": trade.symbol,
                    "price": float(trade.p),
                    "size": int(trade.s),
                    "timestamp": str(trade.t),
                }
                self._live_trades[trade.symbol] = data
                
                for callback in self._on_trade_callbacks:
                    await callback(data) if asyncio.iscoroutinefunction(callback) \
                        else callback(data)

            # الاشتراك في الشموع
            @self._stream.on_bar(*symbols)
            async def on_bar(bar):
                data = {
                    "symbol": bar.symbol,
                    "open": float(bar.o),
                    "high": float(bar.h),
                    "low": float(bar.l),
                    "close": float(bar.c),
                    "volume": int(bar.v),
                    "timestamp": str(bar.t),
                }
                self._live_bars[bar.symbol].append(data)
                
                # حافظ على آخر 200 شمعة
                if len(self._live_bars[bar.symbol]) > 200:
                    self._live_bars[bar.symbol] = self._live_bars[bar.symbol][-200:]
                
                for callback in self._on_bar_callbacks:
                    await callback(data) if asyncio.iscoroutinefunction(callback) \
                        else callback(data)

            self._streaming = True
            logger.info(f"📡 بث مباشر مفعل: {', '.join(symbols)}")
            
            self._stream.run()
            
        except Exception as e:
            logger.error(f"❌ خطأ في البث المباشر: {e}")
            self._streaming = False

    def stop_streaming(self):
        """إيقاف البث المباشر"""
        if self._stream:
            try:
                self._stream.stop()
            except:
                pass
        self._streaming = False
        logger.info("📡 البث المباشر متوقف")

    def on_quote(self, callback: Callable):
        """تسجيل callback لتحديثات الأسعار"""
        self._on_quote_callbacks.append(callback)

    def on_trade(self, callback: Callable):
        """تسجيل callback لتحديثات الصفقات"""
        self._on_trade_callbacks.append(callback)

    def on_bar(self, callback: Callable):
        """تسجيل callback لتحديثات الشموع"""
        self._on_bar_callbacks.append(callback)

    def get_live_price(self, symbol: str) -> float:
        """جلب آخر سعر من البث المباشر أو REST"""
        if symbol in self._live_quotes:
            return self._live_quotes[symbol].get("mid", 0)
        if symbol in self._live_trades:
            return self._live_trades[symbol].get("price", 0)
        
        # fallback إلى REST
        quote = self.get_latest_quote(symbol)
        return quote.get("mid", 0)

    # ══════════════════════════════════════════════════════
    # 5. فحص السوق
    # ══════════════════════════════════════════════════════

    def is_market_open(self) -> bool:
        """هل السوق مفتوح؟ (مع كاش 60 ثانية)"""
        cached = self._market_cache.get("is_open")
        if cached and (time.time() - cached["timestamp"]) < 60.0:
            return cached["value"]
        try:
            clock = self.api.get_clock()
            self._market_cache["is_open"] = {
                "value": clock.is_open,
                "timestamp": time.time()
            }
            return clock.is_open
        except Exception as e:
            logger.error(f"❌ خطأ في فحص حالة السوق: {e}")
            return False

    def get_market_calendar(self, days: int = 5) -> List[dict]:
        """جلب تقويم السوق"""
        try:
            start = datetime.now().strftime("%Y-%m-%d")
            end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            calendar = self.api.get_calendar(start=start, end=end)
            return [{
                "date": str(c.date),
                "open": str(c.open),
                "close": str(c.close),
            } for c in calendar]
        except Exception as e:
            logger.error(f"❌ خطأ في جلب التقويم: {e}")
            return []

    def get_market_clock(self) -> dict:
        """جلب ساعة السوق"""
        try:
            clock = self.api.get_clock()
            return {
                "is_open": clock.is_open,
                "next_open": str(clock.next_open),
                "next_close": str(clock.next_close),
                "timestamp": str(clock.timestamp),
            }
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الساعة: {e}")
            return {"is_open": False}

    # ══════════════════════════════════════════════════════
    # 6. تنفيذ الأوامر
    # ══════════════════════════════════════════════════════

    def submit_order(self, symbol: str, qty: int, side: str,
                     order_type: str = "market",
                     limit_price: float = None,
                     stop_price: float = None,
                     time_in_force: str = "day",
                     trail_percent: float = None) -> dict:
        """
        تنفيذ أمر تداول
        
        order_type: market, limit, stop, stop_limit, trailing_stop
        side: buy, sell
        time_in_force: day, gtc, ioc, fok
        """
        try:
            params = {
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "type": order_type,
                "time_in_force": time_in_force,
            }
            
            if limit_price and order_type in ("limit", "stop_limit"):
                params["limit_price"] = str(limit_price)
            if stop_price and order_type in ("stop", "stop_limit"):
                params["stop_price"] = str(stop_price)
            if trail_percent and order_type == "trailing_stop":
                params["trail_percent"] = str(trail_percent)
            
            order = self.api.submit_order(**params)
            
            result = {
                "id": order.id,
                "symbol": order.symbol,
                "qty": int(order.qty),
                "side": order.side,
                "type": order.type,
                "status": order.status,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else 0,
                "created_at": str(order.created_at),
            }
            
            logger.info(
                f"📤 أمر جديد: {side.upper()} {qty}x {symbol} ({order_type}) | "
                f"الحالة: {order.status}"
            )
            
            return result
        except Exception as e:
            logger.error(f"❌ خطأ في تنفيذ الأمر: {e}")
            return {"error": str(e)}

    def submit_bracket_order(self, symbol: str, qty: int, side: str,
                              limit_price: float,
                              take_profit: float,
                              stop_loss: float) -> dict:
        """
        أمر مركب (Bracket Order): دخول + جني أرباح + وقف خسارة
        أفضل طريقة للحماية التلقائية
        """
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type="limit",
                time_in_force="day",
                limit_price=str(limit_price),
                order_class="bracket",
                take_profit={"limit_price": str(take_profit)},
                stop_loss={"stop_price": str(stop_loss)}
            )
            
            result = {
                "id": order.id,
                "symbol": order.symbol,
                "qty": int(order.qty),
                "side": order.side,
                "type": "bracket",
                "status": order.status,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
            }
            
            logger.info(
                f"🔒 أمر مركب: {side.upper()} {qty}x {symbol} @ ${limit_price:.2f} | "
                f"TP: ${take_profit:.2f} | SL: ${stop_loss:.2f}"
            )
            
            return result
        except Exception as e:
            logger.error(f"❌ خطأ في الأمر المركب: {e}")
            return {"error": str(e)}

    def submit_oto_order(self, symbol: str, qty: int, side: str,
                          entry_price: float,
                          trailing_stop_pct: float) -> dict:
        """
        أمر OTO: دخول + وقف متحرك تلقائي
        """
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type="limit",
                time_in_force="day",
                limit_price=str(entry_price),
                order_class="oto",
                stop_loss={
                    "stop_price": str(entry_price * (1 - trailing_stop_pct / 100)),
                    "trail_percent": str(trailing_stop_pct)
                }
            )
            
            return {
                "id": order.id,
                "symbol": order.symbol,
                "status": order.status,
                "trailing_stop_pct": trailing_stop_pct,
            }
        except Exception as e:
            logger.error(f"❌ خطأ في أمر OTO: {e}")
            return {"error": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        """إلغاء أمر"""
        try:
            self.api.cancel_order(order_id)
            logger.info(f"🚫 إلغاء أمر: {order_id}")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ في الإلغاء: {e}")
            return False

    def cancel_all_orders(self) -> bool:
        """إلغاء جميع الأوامر المعلقة"""
        try:
            self.api.cancel_all_orders()
            logger.info("🚫 إلغاء جميع الأوامر")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ في إلغاء الأوامر: {e}")
            return False

    def close_position(self, symbol: str) -> dict:
        """إغلاق مركز"""
        try:
            order = self.api.close_position(symbol)
            logger.info(f"📕 إغلاق مركز: {symbol}")
            return {"symbol": symbol, "status": "closed", "order_id": order.id}
        except Exception as e:
            logger.error(f"❌ خطأ في إغلاق المركز: {e}")
            return {"error": str(e)}

    def close_all_positions(self) -> bool:
        """إغلاق جميع المراكز فوراً"""
        try:
            self.api.close_all_positions()
            logger.info("📕 إغلاق جميع المراكز")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ في إغلاق المراكز: {e}")
            return False

    def get_open_orders(self) -> List[dict]:
        """جلب الأوامر المفتوحة"""
        try:
            orders = self.api.list_orders(status="open")
            return [{
                "id": o.id,
                "symbol": o.symbol,
                "qty": int(o.qty),
                "side": o.side,
                "type": o.type,
                "status": o.status,
                "limit_price": float(o.limit_price) if o.limit_price else None,
                "stop_price": float(o.stop_price) if o.stop_price else None,
            } for o in orders]
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الأوامر: {e}")
            return []

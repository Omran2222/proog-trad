"""
╔══════════════════════════════════════════════════════════════╗
║            محرك التداول الذكي - Smart Trading Engine         ║
║           يربط التحليل الفني بإدارة المخاطر والتنفيذ         ║
╚══════════════════════════════════════════════════════════════╝

الاستراتيجيات:
  1. smart_scalp   - مضاربة سريعة ذكية
  2. trend_follow  - تتبع الاتجاه
  3. mean_revert   - العودة للمتوسط
  4. breakout      - اختراق المستويات
"""

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional
from config import TRADING, RISK
from risk_manager import RiskManager
from technical_analysis import TechnicalAnalyzer, Signal
from data_engine import AlpacaDataEngine

logger = logging.getLogger("TradingEngine")


class SmartTradingEngine:
    """
    ═══════════════════════════════════════════════════════
    محرك التداول الذكي
    يجمع بين التحليل الفني وإدارة المخاطر والتنفيذ السريع
    ═══════════════════════════════════════════════════════
    """

    def __init__(self, data_engine: AlpacaDataEngine,
                 risk_manager: RiskManager,
                 analyzer: TechnicalAnalyzer):
        self.data = data_engine
        self.risk = risk_manager
        self.analyzer = analyzer
        
        # سجل العمليات
        self.executed_signals: List[dict] = []
        self.rejected_signals: List[dict] = []
        self.active_monitors: Dict[str, dict] = {}
        
        logger.info("🧠 محرك التداول الذكي جاهز")

    # ══════════════════════════════════════════════════════
    # 1. المسح والتحليل
    # ══════════════════════════════════════════════════════

    def scan_watchlist(self) -> List[Signal]:
        """مسح قائمة المراقبة وتوليد إشارات - جلب متوازٍ لأقصى سرعة"""
        logger.info(f"🔍 مسح {len(TRADING.watchlist)} سهم... (استراتيجية: {TRADING.strategy})")

        all_bars = {}

        def fetch_bars(symbol):
            if TRADING.strategy == "weekly_swing":
                # الاستراتيجية الأسبوعية تستخدم شموع يومية (250 يوم)
                bars = self.data.get_daily_bars(symbol, days=250)
            else:
                bars = self.data.get_intraday_bars(symbol, minutes=1, limit=100)
            return symbol, bars

        max_workers = min(len(TRADING.watchlist), 10)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_bars, sym): sym for sym in TRADING.watchlist}
            for future in as_completed(futures):
                try:
                    symbol, bars = future.result()
                    if bars:
                        all_bars[symbol] = bars
                except Exception as e:
                    logger.error(f"❌ خطأ في جلب بيانات: {e}")

        signals = self.analyzer.quick_scan(all_bars)

        logger.info(f"📊 تم العثور على {len(signals)} إشارة")
        return signals

    def analyze_symbol(self, symbol: str) -> Optional[Signal]:
        """تحليل سهم محدد"""
        bars = self.data.get_intraday_bars(symbol, minutes=1, limit=100)
        if not bars:
            logger.warning(f"⚠️ لا توجد بيانات كافية لـ {symbol}")
            return None
        
        for b in bars:
            b["symbol"] = symbol
        
        return self.analyzer.analyze(bars)

    # ══════════════════════════════════════════════════════
    # 2. تنفيذ الإشارات
    # ══════════════════════════════════════════════════════

    def execute_signal(self, signal: Signal) -> dict:
        """
        تنفيذ إشارة تداول مع جميع فحوصات الأمان
        
        خطوات التنفيذ:
        1. فحص الإشارة (قوة وثقة)
        2. فحص إدارة المخاطر
        3. فحص السبريد
        4. حساب الحجم الأمثل
        5. تنفيذ بأمر مركب (Bracket)
        6. تسجيل وبدء المراقبة
        """
        result = {"status": "rejected", "reason": "", "signal": signal}
        
        # ─── 1. فحص قوة الإشارة ───────────────────────────
        if signal.direction == "hold":
            result["reason"] = "إشارة حياد - لا تداول"
            self.rejected_signals.append(result)
            return result
        
        if signal.strength < TRADING.min_signal_strength:
            result["reason"] = f"إشارة ضعيفة ({signal.strength:.0%} < {TRADING.min_signal_strength:.0%})"
            self.rejected_signals.append(result)
            return result
        
        if signal.confidence < 0.6:
            result["reason"] = f"ثقة منخفضة ({signal.confidence:.0%})"
            self.rejected_signals.append(result)
            return result

        # ─── 2. جلب السعر الحالي ──────────────────────────
        quote = self.data.get_latest_quote(signal.symbol)
        current_price = quote.get("mid", 0)
        
        if current_price <= 0:
            result["reason"] = "سعر غير متاح"
            self.rejected_signals.append(result)
            return result

        # ─── 3. فحص السبريد ───────────────────────────────
        spread_pct = quote.get("spread_pct", 0)
        if spread_pct > RISK.max_spread_pct:
            result["reason"] = f"سبريد مرتفع ({spread_pct:.2f}% > {RISK.max_spread_pct}%)"
            self.rejected_signals.append(result)
            return result

        # ─── 4. حساب الحجم الأمثل ─────────────────────────
        optimal_qty = self.risk.calculate_position_size(
            current_price, signal.stop_loss
        )
        
        # 🧪 جس النبض (Pulse Check): أول صفقة في اليوم يتم قصرها على سهم واحد لاختبار السوق والبوت
        if self.risk.daily_pnl.total_trades == 0:
            logger.info(f"🧪 جس النبض: أول إشارة لليوم على {signal.symbol} - سيتم الدخول بسهم واحد (1) فقط كاختبار")
            optimal_qty = 1
        
        if optimal_qty <= 0:
            result["reason"] = "حجم الصفقة = 0 (وقف الخسارة قريب جداً)"
            self.rejected_signals.append(result)
            return result

        # ─── 5. فحص إدارة المخاطر ─────────────────────────
        side = signal.direction
        can_trade, reason = self.risk.can_open_trade(
            signal.symbol, current_price, optimal_qty, side
        )
        
        if not can_trade:
            result["reason"] = reason
            self.rejected_signals.append(result)
            logger.warning(f"⛔ رُفضت إشارة {signal.symbol}: {reason}")
            return result

        # ─── 6. تنفيذ الأمر المركب ────────────────────────
        logger.info(
            f"🚀 تنفيذ: {side.upper()} {optimal_qty}x {signal.symbol} "
            f"@ ${current_price:.2f}"
        )
        
        # استخدام Bracket Order للحماية القصوى
        order_result = self.data.submit_bracket_order(
            symbol=signal.symbol,
            qty=optimal_qty,
            side=side,
            limit_price=round(current_price, 2),
            take_profit=round(signal.take_profit, 2),
            stop_loss=round(signal.stop_loss, 2)
        )
        
        if "error" in order_result:
            # حاول بأمر سوق عادي + وقف يدوي
            logger.warning(f"⚠️ فشل الأمر المركب، محاولة أمر سوق...")
            order_result = self.data.submit_order(
                symbol=signal.symbol,
                qty=optimal_qty,
                side=side,
                order_type="market",
                time_in_force="day"
            )
            
            if "error" in order_result:
                result["reason"] = f"فشل التنفيذ: {order_result['error']}"
                self.rejected_signals.append(result)
                return result
            
            # تسجيل وقف يدوي
            needs_manual_stop = True
        else:
            needs_manual_stop = False

        # ─── 7. تسجيل في إدارة المخاطر ───────────────────
        trade = self.risk.register_trade(
            signal.symbol, side, current_price, optimal_qty
        )

        # ─── 8. بدء المراقبة ──────────────────────────────
        self.active_monitors[signal.symbol] = {
            "trade": trade,
            "signal": signal,
            "order": order_result,
            "needs_manual_stop": needs_manual_stop,
            "entry_time": datetime.now().isoformat(),
        }

        result = {
            "status": "executed",
            "symbol": signal.symbol,
            "side": side,
            "qty": optimal_qty,
            "price": current_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "order_id": order_result.get("id", ""),
            "signal_strength": signal.strength,
            "signal_confidence": signal.confidence,
        }
        
        self.executed_signals.append(result)
        
        logger.info(
            f"✅ تم التنفيذ: {side.upper()} {optimal_qty}x {signal.symbol} "
            f"@ ${current_price:.2f} | SL: ${signal.stop_loss:.2f} | "
            f"TP: ${signal.take_profit:.2f}"
        )
        
        return result

    # ══════════════════════════════════════════════════════
    # 3. مراقبة الصفقات المفتوحة
    # ══════════════════════════════════════════════════════

    def monitor_positions(self) -> List[dict]:
        """مراقبة جميع الصفقات المفتوحة وتحديث الحماية"""
        actions = []

        symbols = list(self.risk.open_trades.keys())
        if not symbols:
            return actions

        # جلب أسعار جميع المراكز دفعة واحدة (أسرع بكثير)
        if len(symbols) > 1:
            multi_quotes = self.data.get_multi_quotes(symbols)
        else:
            multi_quotes = {}

        for symbol in symbols:
            # استخدام السعر المُجمَّع أو fallback للسعر المباشر
            if symbol in multi_quotes:
                price = multi_quotes[symbol].get("mid", 0)
            else:
                price = self.data.get_live_price(symbol)

            if price <= 0:
                continue

            # تحديث في إدارة المخاطر
            action = self.risk.update_trade(symbol, price)

            if action:
                actions.append({
                    "symbol": symbol,
                    "action": action,
                    "price": price,
                })

                # تنفيذ الإجراء
                if action in ("close_loss", "close_profit", "emergency_close"):
                    self._close_position(symbol, price, action)

        return actions

    def _close_position(self, symbol: str, price: float, reason: str):
        """إغلاق مركز"""
        # إغلاق من Alpaca
        close_result = self.data.close_position(symbol)
        
        # تسجيل في إدارة المخاطر
        self.risk.close_trade(symbol, price, reason)
        
        # إزالة من المراقبة
        if symbol in self.active_monitors:
            del self.active_monitors[symbol]
        
        emoji = {
            "close_profit": "🎯💚",
            "close_loss": "🛑🔴",
            "emergency_close": "🆘⚠️"
        }.get(reason, "📕")
        
        logger.info(f"{emoji} إغلاق {symbol} @ ${price:.2f} | السبب: {reason}")

    # ══════════════════════════════════════════════════════
    # 4. الاستراتيجيات
    # ══════════════════════════════════════════════════════

    def run_smart_scalp(self):
        """
        استراتيجية المضاربة الذكية:
        - مسح سريع للأسهم
        - تنفيذ أقوى الإشارات فقط
        - وقف خسارة ضيق
        - جني أرباح سريع
        """
        logger.info("🎯 تشغيل استراتيجية المضاربة الذكية")
        
        # 1. مسح
        signals = self.scan_watchlist()
        
        # 2. فلترة أقوى الإشارات
        strong = [s for s in signals if s.strength >= TRADING.min_signal_strength]
        
        if not strong:
            logger.info("⚪ لا توجد إشارات قوية حالياً")
            return []
        
        # 3. تنفيذ (واحدة تلو الأخرى مع فحص المخاطر)
        results = []
        for signal in strong[:3]:  # أقصى 3 صفقات في الجولة
            result = self.execute_signal(signal)
            results.append(result)
            
            if result["status"] != "executed":
                continue
            
            time.sleep(0.5)  # تأخير بسيط بين الأوامر
        
        return results

    def run_trend_follow(self):
        """استراتيجية تتبع الاتجاه"""
        logger.info("📈 تشغيل استراتيجية تتبع الاتجاه")
        
        signals = self.scan_watchlist()
        
        # فقط إشارات مع اتجاه واضح (EMA trend)
        trend_signals = []
        for s in signals:
            ema_t = s.indicators.get("ema_trend", 0)
            if ema_t > 0:
                if s.direction == "buy" and s.entry_price > ema_t:
                    trend_signals.append(s)
                elif s.direction == "sell" and s.entry_price < ema_t:
                    trend_signals.append(s)
        
        results = []
        for signal in trend_signals[:2]:
            result = self.execute_signal(signal)
            results.append(result)
        
        return results

    def run_mean_revert(self):
        """استراتيجية العودة للمتوسط"""
        logger.info("🔄 تشغيل استراتيجية العودة للمتوسط")
        
        signals = self.scan_watchlist()
        
        # فقط إشارات قرب بولينجر bands
        revert_signals = []
        for s in signals:
            bb_lower = s.indicators.get("bollinger_lower", 0)
            bb_upper = s.indicators.get("bollinger_upper", 0)
            
            if bb_lower > 0 and bb_upper > 0:
                if s.direction == "buy" and s.entry_price <= bb_lower * 1.01:
                    revert_signals.append(s)
                elif s.direction == "sell" and s.entry_price >= bb_upper * 0.99:
                    revert_signals.append(s)
        
        results = []
        for signal in revert_signals[:2]:
            result = self.execute_signal(signal)
            results.append(result)
        
        return results

    # ══════════════════════════════════════════════════════
    # 5. الحلقة الرئيسية
    # ══════════════════════════════════════════════════════

    def run_cycle(self) -> Dict:
        """دورة تداول واحدة"""
        cycle_start = time.time()
        
        # 0. تحديث/تصفير اليوم (لمضاهاة الأرباح والخسائر اليومية للمضارب اليومي)
        if self.risk.daily_pnl.date != datetime.now().strftime("%Y-%m-%d"):
            self.risk.reset_daily()
            logger.info("🌅 يوم تداول جديد! تم تصفير إحصائيات المحفظة اليومية.")

        # 1. مراقبة الصفقات المفتوحة أولاً
        monitor_actions = self.monitor_positions()
        
        # 2. تشغيل الاستراتيجية
        strategy_func = {
            "smart_scalp": self.run_smart_scalp,
            "trend_follow": self.run_trend_follow,
            "mean_revert": self.run_mean_revert,
        }.get(TRADING.strategy, self.run_smart_scalp)
        
        trade_results = strategy_func()
        
        cycle_time = time.time() - cycle_start
        
        return {
            "cycle_time_ms": int(cycle_time * 1000),
            "monitor_actions": len(monitor_actions),
            "new_trades": len([r for r in trade_results if r.get("status") == "executed"]),
            "rejected": len([r for r in trade_results if r.get("status") == "rejected"]),
            "open_positions": len(self.risk.open_trades),
            "timestamp": datetime.now().isoformat()
        }

    # ══════════════════════════════════════════════════════
    # 6. أوامر سريعة
    # ══════════════════════════════════════════════════════

    def quick_buy(self, symbol: str, qty: int = None) -> dict:
        """شراء سريع مع حماية تلقائية"""
        quote = self.data.get_latest_quote(symbol)
        price = quote.get("mid", 0)
        
        if price <= 0:
            return {"error": f"سعر {symbol} غير متاح"}
        
        levels = self.risk.calculate_stop_levels(price, "buy")
        
        if qty is None:
            qty = self.risk.calculate_position_size(price, levels["stop_loss"])
        
        if qty <= 0:
            return {"error": "حجم الصفقة = 0"}
        
        can_trade, reason = self.risk.can_open_trade(symbol, price, qty, "buy")
        if not can_trade:
            return {"error": reason}
        
        order = self.data.submit_bracket_order(
            symbol, qty, "buy",
            limit_price=round(price, 2),
            take_profit=levels["take_profit"],
            stop_loss=levels["stop_loss"]
        )
        
        if "error" not in order:
            self.risk.register_trade(symbol, "buy", price, qty)
        
        return {**order, "levels": levels, "qty": qty, "price": price}

    def quick_sell(self, symbol: str) -> dict:
        """بيع/إغلاق سريع"""
        return self.data.close_position(symbol)

    def emergency_exit(self) -> dict:
        """خروج طوارئ - إغلاق كل شيء"""
        logger.critical("🆘 خروج طوارئ!")
        
        # إلغاء جميع الأوامر
        self.data.cancel_all_orders()
        
        # إغلاق جميع المراكز
        self.data.close_all_positions()
        
        # إغلاق في إدارة المخاطر
        closed = self.risk.emergency_close_all()
        
        return {
            "status": "emergency_exit",
            "closed_trades": len(closed),
            "message": "تم إغلاق جميع الصفقات والأوامر"
        }

    def get_status(self) -> Dict:
        """حالة المحرك الشاملة"""
        portfolio = self.risk.get_portfolio_status()
        
        return {
            "portfolio": portfolio,
            "strategy": TRADING.strategy,
            "open_monitors": len(self.active_monitors),
            "total_executed": len(self.executed_signals),
            "total_rejected": len(self.rejected_signals),
            "market_open": self.data.is_market_open(),
        }

"""
╔══════════════════════════════════════════════════════════════╗
║           محرك التحليل الفني - Technical Analysis            ║
║            المؤشرات الفنية لتحليل دقيق للسوق               ║
╚══════════════════════════════════════════════════════════════╝

مؤشرات مستخدمة:
  - RSI (مؤشر القوة النسبية)
  - EMA (متوسط متحرك أسي)
  - MACD (تقارب/تباعد المتوسطات)
  - Bollinger Bands (أشرطة بولينجر)
  - VWAP (متوسط السعر المرجح بالحجم)
  - ATR (متوسط المدى الحقيقي)
  - Volume Analysis (تحليل الحجم)
"""

import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from config import TRADING, RISK

logger = logging.getLogger("TechAnalysis")


@dataclass
class Signal:
    """إشارة تداول"""
    symbol: str
    direction: str          # "buy", "sell", "hold"
    strength: float         # 0.0 - 1.0
    reason: str
    indicators: Dict        # المؤشرات المستخدمة
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float       # 0.0 - 1.0


class TechnicalAnalyzer:
    """
    ═══════════════════════════════════════════════════════
    محرك التحليل الفني - تحليل دقيق بدون مكتبات خارجية
    ═══════════════════════════════════════════════════════
    """

    def __init__(self):
        logger.info("📊 محرك التحليل الفني جاهز")

    # ══════════════════════════════════════════════════════
    # 1. المؤشرات الأساسية
    # ══════════════════════════════════════════════════════

    @staticmethod
    def calc_sma(data: List[float], period: int) -> List[float]:
        """متوسط متحرك بسيط SMA"""
        if len(data) < period:
            return []
        result = []
        for i in range(period - 1, len(data)):
            window = data[i - period + 1:i + 1]
            result.append(sum(window) / period)
        return result

    @staticmethod
    def calc_ema(data: List[float], period: int) -> List[float]:
        """متوسط متحرك أسي EMA - أسرع استجابة"""
        if len(data) < period:
            return []
        
        multiplier = 2.0 / (period + 1)
        # أول قيمة = SMA
        ema = [sum(data[:period]) / period]
        
        for i in range(period, len(data)):
            new_ema = (data[i] - ema[-1]) * multiplier + ema[-1]
            ema.append(new_ema)
        
        return ema

    @staticmethod
    def calc_rsi(closes: List[float], period: int = 14) -> List[float]:
        """مؤشر القوة النسبية RSI"""
        if len(closes) < period + 1:
            return []
        
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        
        gains = [max(d, 0) for d in deltas]
        losses = [abs(min(d, 0)) for d in deltas]
        
        # أول متوسط
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        rsi_values = []
        
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))
        
        # باقي القيم (Wilder's smoothing)
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
            if avg_loss == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100 - (100 / (1 + rs)))
        
        return rsi_values

    @staticmethod
    def calc_macd(closes: List[float],
                  fast: int = 12, slow: int = 26,
                  signal_period: int = 9) -> Dict[str, List[float]]:
        """MACD - تقارب/تباعد المتوسطات المتحركة"""
        if len(closes) < slow + signal_period:
            return {"macd": [], "signal": [], "histogram": []}
        
        ema_fast = TechnicalAnalyzer.calc_ema(closes, fast)
        ema_slow = TechnicalAnalyzer.calc_ema(closes, slow)
        
        # محاذاة الأطوال
        diff = len(ema_fast) - len(ema_slow)
        ema_fast_aligned = ema_fast[diff:]
        
        macd_line = [f - s for f, s in zip(ema_fast_aligned, ema_slow)]
        signal_line = TechnicalAnalyzer.calc_ema(macd_line, signal_period)
        
        # محاذاة
        diff2 = len(macd_line) - len(signal_line)
        macd_aligned = macd_line[diff2:]
        
        histogram = [m - s for m, s in zip(macd_aligned, signal_line)]
        
        return {
            "macd": macd_aligned,
            "signal": signal_line,
            "histogram": histogram
        }

    @staticmethod
    def calc_bollinger(closes: List[float], period: int = 20,
                       std_dev: float = 2.0) -> Dict[str, List[float]]:
        """أشرطة بولينجر"""
        if len(closes) < period:
            return {"upper": [], "middle": [], "lower": [], "width": []}
        
        middle = TechnicalAnalyzer.calc_sma(closes, period)
        
        upper = []
        lower = []
        width = []
        
        for i in range(len(middle)):
            idx = i + period - 1
            window = closes[idx - period + 1:idx + 1]
            
            mean = middle[i]
            variance = sum((x - mean) ** 2 for x in window) / period
            std = variance ** 0.5
            
            u = mean + std_dev * std
            l = mean - std_dev * std
            
            upper.append(u)
            lower.append(l)
            width.append((u - l) / mean * 100 if mean > 0 else 0)
        
        return {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "width": width
        }

    @staticmethod
    def calc_vwap(highs: List[float], lows: List[float],
                  closes: List[float], volumes: List[int]) -> List[float]:
        """VWAP - متوسط السعر المرجح بالحجم"""
        if not highs or len(highs) != len(lows) != len(closes) != len(volumes):
            return []
        
        vwap = []
        cumulative_tp_vol = 0
        cumulative_vol = 0
        
        for i in range(len(closes)):
            typical_price = (highs[i] + lows[i] + closes[i]) / 3
            cumulative_tp_vol += typical_price * volumes[i]
            cumulative_vol += volumes[i]
            
            if cumulative_vol > 0:
                vwap.append(cumulative_tp_vol / cumulative_vol)
            else:
                vwap.append(typical_price)
        
        return vwap

    @staticmethod
    def calc_atr(highs: List[float], lows: List[float],
                 closes: List[float], period: int = 14) -> List[float]:
        """ATR - متوسط المدى الحقيقي (لحساب التقلبات)"""
        if len(closes) < period + 1:
            return []
        
        true_ranges = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            true_ranges.append(tr)
        
        # أول ATR = SMA
        atr = [sum(true_ranges[:period]) / period]
        
        for i in range(period, len(true_ranges)):
            new_atr = (atr[-1] * (period - 1) + true_ranges[i]) / period
            atr.append(new_atr)
        
        return atr

    @staticmethod
    def calc_volume_profile(volumes: List[int], period: int = 20) -> Dict:
        """تحليل الحجم"""
        if len(volumes) < period:
            return {"avg_volume": 0, "volume_ratio": 0, "volume_trend": "neutral"}
        
        recent = volumes[-period:]
        avg = sum(recent) / len(recent)
        current = volumes[-1]
        
        ratio = current / avg if avg > 0 else 0
        
        trend = "neutral"
        if ratio > 1.5:
            trend = "high"
        elif ratio > 1.2:
            trend = "above_average"
        elif ratio < 0.5:
            trend = "low"
        elif ratio < 0.8:
            trend = "below_average"
        
        return {
            "avg_volume": avg,
            "current_volume": current,
            "volume_ratio": ratio,
            "volume_trend": trend
        }

    # ══════════════════════════════════════════════════════
    # 2. تحليل شامل وتوليد إشارات
    # ══════════════════════════════════════════════════════

    def analyze(self, bars: List[dict]) -> Optional[Signal]:
        """
        تحليل شامل لسهم وتوليد إشارة تداول
        
        bars: قائمة شموع (كل شمعة تحتوي: open, high, low, close, volume)
        """
        if len(bars) < 50:
            logger.warning("⚠️ بيانات غير كافية للتحليل (أقل من 50 شمعة)")
            return None
        
        symbol = bars[0].get("symbol", "UNKNOWN") if "symbol" in bars[0] else "UNKNOWN"
        
        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        volumes = [b["volume"] for b in bars]
        
        current_price = closes[-1]
        
        # ─── حساب جميع المؤشرات ──────────────────────────
        rsi = self.calc_rsi(closes, TRADING.rsi_period)
        ema_fast = self.calc_ema(closes, TRADING.ema_fast)
        ema_slow = self.calc_ema(closes, TRADING.ema_slow)
        ema_trend = self.calc_ema(closes, TRADING.ema_trend)
        macd = self.calc_macd(closes, TRADING.macd_fast, TRADING.macd_slow, TRADING.macd_signal)
        bollinger = self.calc_bollinger(closes, TRADING.bollinger_period, TRADING.bollinger_std)
        atr = self.calc_atr(highs, lows, closes)
        vol_profile = self.calc_volume_profile(volumes)
        
        if TRADING.vwap_enabled:
            vwap = self.calc_vwap(highs, lows, closes, volumes)
        else:
            vwap = []
        
        # ─── نظام التسجيل ─────────────────────────────────
        buy_score = 0
        sell_score = 0
        reasons = []
        max_score = 7  # عدد المؤشرات

        # 1. RSI
        if rsi:
            current_rsi = rsi[-1]
            if current_rsi < TRADING.rsi_oversold:
                buy_score += 1
                reasons.append(f"RSI مُشبع بيع ({current_rsi:.0f})")
            elif current_rsi > TRADING.rsi_overbought:
                sell_score += 1
                reasons.append(f"RSI مُشبع شراء ({current_rsi:.0f})")
            elif current_rsi < 45:
                buy_score += 0.5
            elif current_rsi > 55:
                sell_score += 0.5

        # 2. EMA التقاطع
        if ema_fast and ema_slow:
            if ema_fast[-1] > ema_slow[-1]:
                buy_score += 1
                if len(ema_fast) > 1 and len(ema_slow) > 1:
                    if ema_fast[-2] <= ema_slow[-2]:
                        buy_score += 0.5
                        reasons.append("تقاطع ذهبي EMA")
            else:
                sell_score += 1
                if len(ema_fast) > 1 and len(ema_slow) > 1:
                    if ema_fast[-2] >= ema_slow[-2]:
                        sell_score += 0.5
                        reasons.append("تقاطع ميت EMA")

        # 3. EMA الاتجاه
        if ema_trend:
            if current_price > ema_trend[-1]:
                buy_score += 1
                reasons.append("فوق EMA الاتجاه")
            else:
                sell_score += 1
                reasons.append("تحت EMA الاتجاه")

        # 4. MACD
        if macd["histogram"]:
            hist = macd["histogram"][-1]
            if hist > 0:
                buy_score += 1
                if len(macd["histogram"]) > 1 and macd["histogram"][-2] <= 0:
                    buy_score += 0.5
                    reasons.append("MACD تحول إيجابي")
            else:
                sell_score += 1
                if len(macd["histogram"]) > 1 and macd["histogram"][-2] >= 0:
                    sell_score += 0.5
                    reasons.append("MACD تحول سلبي")

        # 5. بولينجر
        if bollinger["lower"] and bollinger["upper"]:
            if current_price <= bollinger["lower"][-1]:
                buy_score += 1
                reasons.append("أسفل بولينجر السفلي")
            elif current_price >= bollinger["upper"][-1]:
                sell_score += 1
                reasons.append("أعلى بولينجر العلوي")
            elif current_price < bollinger["middle"][-1]:
                buy_score += 0.3

        # 6. VWAP
        if vwap:
            if current_price > vwap[-1]:
                buy_score += 0.5
                reasons.append("فوق VWAP")
            else:
                sell_score += 0.5
                reasons.append("تحت VWAP")

        # 7. الحجم
        if vol_profile["volume_trend"] in ("high", "above_average"):
            # الحجم العالي يعزز الاتجاه الحالي
            if buy_score > sell_score:
                buy_score += 1
                reasons.append("حجم تداول مرتفع يدعم الشراء")
            elif sell_score > buy_score:
                sell_score += 1
                reasons.append("حجم تداول مرتفع يدعم البيع")

        # ─── تحديد الإشارة ─────────────────────────────────
        buy_strength = buy_score / max_score
        sell_strength = sell_score / max_score
        
        # ATR لحساب مستويات الحماية
        current_atr = atr[-1] if atr else current_price * 0.02
        
        if buy_strength >= TRADING.min_signal_strength and buy_strength > sell_strength:
            direction = "buy"
            strength = buy_strength
            stop_loss = current_price - (current_atr * 1.5)
            take_profit = current_price + (current_atr * 2.5)
        elif sell_strength >= TRADING.min_signal_strength and sell_strength > buy_strength:
            direction = "sell"
            strength = sell_strength
            stop_loss = current_price + (current_atr * 1.5)
            take_profit = current_price - (current_atr * 2.5)
        else:
            direction = "hold"
            strength = max(buy_strength, sell_strength)
            stop_loss = current_price
            take_profit = current_price
        
        # ─── حساب الثقة ────────────────────────────────────
        confidence = strength
        if len(reasons) >= 3:
            confidence = min(1.0, confidence + 0.1)
        if vol_profile["volume_trend"] in ("high", "above_average"):
            confidence = min(1.0, confidence + 0.05)

        indicators = {
            "rsi": rsi[-1] if rsi else 0,
            "ema_fast": ema_fast[-1] if ema_fast else 0,
            "ema_slow": ema_slow[-1] if ema_slow else 0,
            "ema_trend": ema_trend[-1] if ema_trend else 0,
            "macd_histogram": macd["histogram"][-1] if macd["histogram"] else 0,
            "bollinger_upper": bollinger["upper"][-1] if bollinger["upper"] else 0,
            "bollinger_lower": bollinger["lower"][-1] if bollinger["lower"] else 0,
            "atr": current_atr,
            "vwap": vwap[-1] if vwap else 0,
            "volume_ratio": vol_profile["volume_ratio"],
        }

        signal = Signal(
            symbol=symbol,
            direction=direction,
            strength=strength,
            reason=" | ".join(reasons) if reasons else "لا توجد إشارة واضحة",
            indicators=indicators,
            entry_price=current_price,
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            confidence=confidence
        )

        emoji = {"buy": "🟢", "sell": "🔴", "hold": "⚪"}.get(direction, "⚪")
        logger.info(
            f"{emoji} إشارة {symbol}: {direction.upper()} | "
            f"القوة: {strength:.0%} | الثقة: {confidence:.0%} | "
            f"{signal.reason}"
        )

        return signal

    def quick_scan(self, bars_dict: Dict[str, List[dict]]) -> List[Signal]:
        """مسح سريع لعدة أسهم"""
        signals = []
        for symbol, bars in bars_dict.items():
            try:
                # إضافة الرمز للشموع
                for b in bars:
                    b["symbol"] = symbol

                # اختيار الاستراتيجية تلقائياً
                if TRADING.strategy == "weekly_swing":
                    signal = self.analyze_weekly_swing(bars)
                else:
                    signal = self.analyze(bars)

                if signal and signal.direction != "hold":
                    signals.append(signal)
            except Exception as e:
                logger.error(f"❌ خطأ في تحليل {symbol}: {e}")

        # ترتيب حسب القوة
        signals.sort(key=lambda s: s.strength, reverse=True)
        return signals

    # ══════════════════════════════════════════════════════
    # 3. استراتيجية المضارب الأسبوعي (Weekly Swing)
    # ══════════════════════════════════════════════════════

    def analyze_weekly_swing(self, bars: List[dict]) -> Optional[Signal]:
        """
        ═══════════════════════════════════════════════════════
        استراتيجية المضارب الأسبوعي - Weekly Swing Strategy
        ═══════════════════════════════════════════════════════

        الهدف: التقاط تحركات 5-15% خلال 2-5 أيام تداول

        الإشارات المستخدمة:
          1. EMA 8 / 21 تقاطع (اتجاه قصير المدى)
          2. EMA 50 / 200 اتجاه رئيسي
          3. RSI (14) بين 40-70 للشراء
          4. MACD تحول إيجابي/سلبي
          5. بولينجر - ضيق الحزمة يسبق حركة قوية
          6. Candle Pattern - شمعة دوجي أو ابتلاع
          7. حجم تداول > 1.5x المتوسط

        وقف الخسارة: 2.5% × ATR
        جني الأرباح: 7% أو 2.8×ATR (أيهما أول)
        """
        if len(bars) < 60:
            return None

        symbol = bars[0].get("symbol", "UNKNOWN")
        closes  = [b["close"]  for b in bars]
        highs   = [b["high"]   for b in bars]
        lows    = [b["low"]    for b in bars]
        volumes = [b["volume"] for b in bars]
        opens   = [b["open"]   for b in bars]

        current_price = closes[-1]

        # ─── المؤشرات ─────────────────────────────────────
        rsi        = self.calc_rsi(closes, 14)
        ema8       = self.calc_ema(closes, 8)
        ema21      = self.calc_ema(closes, 21)
        ema50      = self.calc_ema(closes, 50)
        ema200     = self.calc_ema(closes, 200) if len(closes) >= 200 else []
        macd_data  = self.calc_macd(closes, 12, 26, 9)
        boll       = self.calc_bollinger(closes, 20, 2.0)
        atr_vals   = self.calc_atr(highs, lows, closes, 14)
        vol_info   = self.calc_volume_profile(volumes, 20)

        if not (rsi and ema8 and ema21 and ema50 and atr_vals):
            return None

        cur_rsi       = rsi[-1]
        cur_ema8      = ema8[-1]
        cur_ema21     = ema21[-1]
        cur_ema50     = ema50[-1]
        cur_atr       = atr_vals[-1]
        cur_macd_hist = macd_data["histogram"][-1] if macd_data["histogram"] else 0
        prev_macd_hist= macd_data["histogram"][-2] if len(macd_data["histogram"]) > 1 else 0

        # اتجاه السوق الكبير (EMA200 إن توفر)
        above_ema200 = current_price > ema200[-1] if ema200 else True  # افتراض صاعد إن لم تكفِ البيانات

        buy_score  = 0.0
        sell_score = 0.0
        reasons    = []

        # ── 1. تقاطع EMA 8/21 ──────────────────────────────
        if cur_ema8 > cur_ema21:
            buy_score += 1.5
            # تقاطع حديث (خلال آخر شمعتين)
            if len(ema8) > 1 and len(ema21) > 1 and ema8[-2] <= ema21[-2]:
                buy_score += 1.0
                reasons.append("✅ تقاطع EMA 8/21 ذهبي حديث")
        else:
            sell_score += 1.5
            if len(ema8) > 1 and len(ema21) > 1 and ema8[-2] >= ema21[-2]:
                sell_score += 1.0
                reasons.append("🔻 تقاطع EMA 8/21 ميت حديث")

        # ── 2. الاتجاه الرئيسي EMA50 ──────────────────────
        if current_price > cur_ema50:
            buy_score += 1.0
            reasons.append("📈 فوق EMA50 (اتجاه صاعد)")
        else:
            sell_score += 1.0
            reasons.append("📉 تحت EMA50 (اتجاه هابط)")

        # ── 3. EMA200 (فلتر الاتجاه الكبير) ───────────────
        if above_ema200:
            buy_score += 0.5
        else:
            sell_score += 0.5

        # ── 4. RSI (للأسبوعي: نطاق أوسع) ─────────────────
        if 40 <= cur_rsi <= 60:
            # منطقة وسط = لا إشارة قوية
            pass
        elif cur_rsi < 40:
            buy_score  += 1.5
            reasons.append(f"📊 RSI منطقة تشبع بيع ({cur_rsi:.0f})")
        elif cur_rsi > 65:
            sell_score += 1.5
            reasons.append(f"📊 RSI منطقة تشبع شراء ({cur_rsi:.0f})")
        elif 60 <= cur_rsi <= 65:
            buy_score += 0.5   # زخم إيجابي لكن لم يصل الذروة

        # ── 5. MACD تحول ──────────────────────────────────
        if cur_macd_hist > 0:
            buy_score += 1.0
            if prev_macd_hist <= 0:
                buy_score += 1.0
                reasons.append("⚡ MACD تحول إيجابي (تقاطع)")
        else:
            sell_score += 1.0
            if prev_macd_hist >= 0:
                sell_score += 1.0
                reasons.append("⚡ MACD تحول سلبي (تقاطع)")

        # ── 6. بولينجر - اختراق وضغط ─────────────────────
        if boll["lower"] and boll["upper"] and boll["width"]:
            band_squeeze = boll["width"][-1] < 3.0   # حزمة ضيقة → انفجار قادم
            if current_price > boll["upper"][-1]:
                sell_score += 1.0
                reasons.append("🔴 اختراق بولينجر العلوي (بيع محتمل)")
            elif current_price < boll["lower"][-1]:
                buy_score  += 1.0
                reasons.append("🟢 أسفل بولينجر السفلي (شراء محتمل)")
            if band_squeeze:
                # الحزمة الضيقة تعزز أي اتجاه
                if buy_score > sell_score:
                    buy_score  += 0.5
                    reasons.append("🔥 ضغط بولينجر يدعم الصعود")
                elif sell_score > buy_score:
                    sell_score += 0.5
                    reasons.append("🔥 ضغط بولينجر يدعم الهبوط")

        # ── 7. نمط الشموع (آخر 3 شموع) ───────────────────
        if len(closes) >= 3:
            # شمعة ابتلاع صاعدة
            prev_body  = closes[-2] - opens[-2]
            cur_body   = closes[-1] - opens[-1]
            if prev_body < 0 and cur_body > 0 and abs(cur_body) > abs(prev_body) * 1.2:
                buy_score += 1.0
                reasons.append("🕯️ شمعة ابتلاع صاعدة")
            # شمعة ابتلاع هابطة
            elif prev_body > 0 and cur_body < 0 and abs(cur_body) > abs(prev_body) * 1.2:
                sell_score += 1.0
                reasons.append("🕯️ شمعة ابتلاع هابطة")
            # هامر (Hammer) للشراء
            lower_shadow = opens[-1] - lows[-1] if opens[-1] > closes[-1] else closes[-1] - lows[-1]
            upper_shadow = highs[-1] - (opens[-1] if opens[-1] > closes[-1] else closes[-1])
            body_size    = abs(cur_body)
            if lower_shadow > body_size * 2 and upper_shadow < body_size * 0.5 and body_size > 0:
                buy_score += 0.8
                reasons.append("🔨 نمط هامر (ارتداد صاعد)")

        # ── 8. حجم التداول (فلتر تأكيد) ──────────────────
        if vol_info["volume_ratio"] > 1.5:
            if buy_score > sell_score:
                buy_score  += 1.0
                reasons.append(f"📦 حجم مرتفع {vol_info['volume_ratio']:.1f}x يدعم الصعود")
            elif sell_score > buy_score:
                sell_score += 1.0
                reasons.append(f"📦 حجم مرتفع {vol_info['volume_ratio']:.1f}x يدعم الهبوط")
        elif vol_info["volume_ratio"] < 0.5:
            # حجم منخفض جداً = إشارة ضعيفة
            buy_score  *= 0.7
            sell_score *= 0.7

        # ── تحديد الإشارة ─────────────────────────────────
        max_score   = 10.0
        buy_strength  = min(buy_score  / max_score, 1.0)
        sell_strength = min(sell_score / max_score, 1.0)

        # وقف الخسارة وجني الأرباح الصارمان للأسبوعي
        sl_atr_mult = 2.5     # وقف الخسارة 2.5× ATR
        tp_atr_mult = 7.0     # جني الأرباح 7× ATR (نسبة R:R ≈ 1:2.8)
        sl_pct      = RISK.default_stop_loss_pct / 100  # 2.5%
        tp_pct      = RISK.take_profit_pct / 100        # 7%

        if buy_strength >= TRADING.min_signal_strength and buy_strength > sell_strength:
            direction   = "buy"
            strength    = buy_strength
            # وقف الخسارة: أيهما أكبر (حماية ATR أو النسبة المئوية)
            sl_by_atr   = current_price - (cur_atr * sl_atr_mult)
            sl_by_pct   = current_price * (1 - sl_pct)
            stop_loss   = max(sl_by_atr, sl_by_pct)   # الأعلى = الأضيق = الأأمن
            # جني الأرباح: أيهما أقل (الأقرب)
            tp_by_atr   = current_price + (cur_atr * tp_atr_mult)
            tp_by_pct   = current_price * (1 + tp_pct)
            take_profit = min(tp_by_atr, tp_by_pct)

        elif sell_strength >= TRADING.min_signal_strength and sell_strength > buy_strength:
            direction   = "sell"
            strength    = sell_strength
            sl_by_atr   = current_price + (cur_atr * sl_atr_mult)
            sl_by_pct   = current_price * (1 + sl_pct)
            stop_loss   = min(sl_by_atr, sl_by_pct)   # الأدنى = الأضيق
            tp_by_atr   = current_price - (cur_atr * tp_atr_mult)
            tp_by_pct   = current_price * (1 - tp_pct)
            take_profit = max(tp_by_atr, tp_by_pct)

        else:
            return Signal(
                symbol=symbol, direction="hold",
                strength=max(buy_strength, sell_strength),
                reason="لا توجد إشارة أسبوعية واضحة",
                indicators={}, entry_price=current_price,
                stop_loss=current_price, take_profit=current_price,
                confidence=0.0
            )

        # الثقة
        confirmed_reasons = len(reasons)
        confidence = min(strength + (confirmed_reasons * 0.04), 1.0)
        if vol_info["volume_ratio"] > 2.0:
            confidence = min(confidence + 0.05, 1.0)

        indicators = {
            "rsi": cur_rsi,
            "ema8": cur_ema8,
            "ema21": cur_ema21,
            "ema50": cur_ema50,
            "macd_hist": cur_macd_hist,
            "atr": cur_atr,
            "volume_ratio": vol_info["volume_ratio"],
            "above_ema200": above_ema200,
        }

        emoji = "🟢" if direction == "buy" else "🔴"
        logger.info(
            f"{emoji} [أسبوعي] {symbol}: {direction.upper()} | "
            f"قوة: {strength:.0%} | ثقة: {confidence:.0%} | "
            f"SL: ${stop_loss:.2f} | TP: ${take_profit:.2f} | "
            f"{' | '.join(reasons[:3])}"
        )

        return Signal(
            symbol=symbol,
            direction=direction,
            strength=strength,
            reason=" | ".join(reasons) if reasons else "إشارة أسبوعية بدون سبب محدد",
            indicators=indicators,
            entry_price=current_price,
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            confidence=confidence
        )


    def get_market_sentiment(self, bars_dict: Dict[str, List[dict]]) -> Dict:
        """تقييم المزاج العام للسوق"""
        bullish = 0
        bearish = 0
        neutral = 0
        total = len(bars_dict)
        
        for symbol, bars in bars_dict.items():
            if len(bars) < 2:
                neutral += 1
                continue
            
            change = (bars[-1]["close"] - bars[-2]["close"]) / bars[-2]["close"] * 100
            if change > 0.5:
                bullish += 1
            elif change < -0.5:
                bearish += 1
            else:
                neutral += 1
        
        sentiment = "neutral"
        if bullish > bearish * 1.5:
            sentiment = "bullish"
        elif bearish > bullish * 1.5:
            sentiment = "bearish"
        
        return {
            "sentiment": sentiment,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "total": total,
            "bullish_pct": (bullish / total * 100) if total > 0 else 0,
            "bearish_pct": (bearish / total * 100) if total > 0 else 0,
        }

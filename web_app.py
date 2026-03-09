"""
╔══════════════════════════════════════════════════════════════╗
║         Smart Scalper Bot - Web Dashboard                    ║
║         FastAPI + WebSocket + Real-time Updates              ║
║         Production-Ready: 24/7 Auto-Trading                  ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import List, Set

import secrets
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request

from config import TRADING, RISK, PAPER_TRADING
from data_engine import AlpacaDataEngine
from risk_manager import RiskManager
from technical_analysis import TechnicalAnalyzer
from trading_engine import SmartTradingEngine
from loss_guardian import LossGuardian

# ── Environment Variables ─────────────────────────────────────
AUTO_START_TRADING = os.getenv("AUTO_START_TRADING", "false").lower() == "true"
AUTO_RESTART_ON_CRASH = os.getenv("AUTO_RESTART_ON_CRASH", "true").lower() == "true"
MAX_RESTART_ATTEMPTS = int(os.getenv("MAX_RESTART_ATTEMPTS", "10"))

# ── Auth ─────────────────────────────────────────────────────
BOT_PASSWORD = os.getenv("BOT_PASSWORD", "")
valid_sessions: set = set()

_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>تسجيل الدخول - Proog Trad</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 flex items-center justify-center min-h-screen">
<div class="bg-slate-800 border border-slate-700 rounded-xl p-8 w-full max-w-sm shadow-2xl">
  <div class="text-center mb-6">
    <div class="text-5xl mb-3">🤖</div>
    <h1 class="text-2xl font-bold text-indigo-400">Proog Trad Bot</h1>
    <p class="text-slate-500 text-sm mt-1">لوحة تحكم خاصة</p>
  </div>
  {error}
  <form method="post" action="/login">
    <label class="block text-slate-400 text-sm mb-2">كلمة المرور</label>
    <input type="password" name="password" autofocus required placeholder="••••••••"
      class="w-full bg-slate-700 text-white border border-slate-600 rounded-lg px-4 py-3 mb-4 focus:outline-none focus:border-indigo-500 text-right">
    <button type="submit"
      class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 rounded-lg transition">
      دخول
    </button>
  </form>
</div>
</body>
</html>
"""


class AuthMiddleware(BaseHTTPMiddleware):
    OPEN = {"/login", "/health", "/favicon.ico"}

    async def dispatch(self, request, call_next):
        if not BOT_PASSWORD:
            return await call_next(request)
        path = request.url.path
        if path in self.OPEN or path.startswith("/static"):
            return await call_next(request)
        token = request.cookies.get("bot_session")
        if token and token in valid_sessions:
            return await call_next(request)
        if request.headers.get("upgrade", "").lower() == "websocket":
            from starlette.responses import Response
            return Response(status_code=403)
        return RedirectResponse("/login", status_code=302)


def _is_authenticated_token(token: str | None) -> bool:
    if not BOT_PASSWORD:
        return True
    return bool(token and token in valid_sessions)

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s │ %(name)-15s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S")
logger = logging.getLogger("WebApp")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app_instance):
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, state.initialize)
    asyncio.create_task(broadcaster())
    # تشغيل حارس التداول المستمر (يراقب حتى لو البوت متوقف)
    asyncio.create_task(watchdog_loop())
    logger.info("🌐 Web Dashboard ready")

    # التشغيل التلقائي عند النشر
    if AUTO_START_TRADING:
        logger.info("🤖 AUTO_START_TRADING enabled - سيبدأ التداول تلقائياً بعد التهيئة")
        asyncio.create_task(_auto_start_after_init())
    yield


async def _auto_start_after_init():
    """انتظار اكتمال التهيئة ثم بدء التداول تلقائياً"""
    for _ in range(60):  # انتظر حتى 60 ثانية
        if state.initialized:
            await asyncio.sleep(2)  # انتظر ثانيتين إضافيتين للاستقرار
            state.start_trading()
            logger.info("🚀 التداول التلقائي بدأ (AUTO_START)")
            return
        await asyncio.sleep(1)
    logger.error("❌ فشل التشغيل التلقائي - التهيئة لم تكتمل")


async def watchdog_loop():
    """
    حارس مستمر: يراقب صحة البوت ويعيد تشغيله عند التعطل.
    يعمل في الخلفية طوال الوقت.
    """
    restart_count = 0
    while True:
        try:
            await asyncio.sleep(30)  # فحص كل 30 ثانية

            if not AUTO_RESTART_ON_CRASH:
                continue

            # إذا كان البوت يفترض أن يعمل لكنه توقف
            if state.initialized and not state.running and AUTO_START_TRADING:
                # تحقق أن التوقف ليس بسبب Circuit Breaker
                if state.guardian and not state.guardian.check_circuit_breaker():
                    if restart_count < MAX_RESTART_ATTEMPTS:
                        restart_count += 1
                        state.add_log("WARNING",
                            f"🔄 Watchdog: إعادة تشغيل البوت (محاولة {restart_count}/{MAX_RESTART_ATTEMPTS})")
                        state.start_trading()
                        logger.warning(f"🔄 Watchdog restarted bot (attempt {restart_count})")
                    else:
                        state.add_log("CRITICAL",
                            f"🚨 Watchdog: وصلنا الحد الأقصى من إعادات التشغيل ({MAX_RESTART_ATTEMPTS})")

            # إعادة تعيين العداد إذا البوت يعمل بنجاح
            if state.running:
                restart_count = 0

        except Exception as e:
            logger.error(f"Watchdog error: {e}")
            await asyncio.sleep(10)


app = FastAPI(title="Smart Scalper Bot", version="2.0", lifespan=lifespan)
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Global Bot State ─────────────────────────────────────────
class BotState:
    def __init__(self):
        self.data_engine: AlpacaDataEngine = None
        self.risk_manager: RiskManager = None
        self.analyzer: TechnicalAnalyzer = None
        self.trading_engine: SmartTradingEngine = None
        self.guardian: LossGuardian = None

        self.running = False
        self._stop_event = threading.Event()
        self._bot_thread: threading.Thread = None

        self.log_buffer: List[dict] = []
        self.signals_buffer: List[dict] = []
        self.last_cycle: dict = {}
        self.initialized = False

    def add_log(self, level: str, message: str):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message
        }
        self.log_buffer.append(entry)
        if len(self.log_buffer) > 100:
            self.log_buffer = self.log_buffer[-100:]

    def initialize(self):
        try:
            self.add_log("INFO", "🤖 تهيئة البوت...")
            self.data_engine = AlpacaDataEngine()
            account = self.data_engine.get_account()
            if not account:
                self.add_log("ERROR", "❌ فشل الاتصال بـ Alpaca API")
                return False

            equity = account.get("equity", 0)
            self.add_log("INFO", f"💰 Equity: ${equity:,.2f}")

            self.risk_manager = RiskManager(equity)
            self.analyzer = TechnicalAnalyzer()
            self.trading_engine = SmartTradingEngine(
                self.data_engine, self.risk_manager, self.analyzer
            )
            self.guardian = LossGuardian(self.data_engine, self.risk_manager)

            # Sync positions
            positions = self.data_engine.get_positions()
            for pos in positions:
                self.risk_manager.register_trade(
                    pos["symbol"], pos["side"],
                    pos["avg_entry_price"], pos["quantity"]
                )
            if positions:
                self.add_log("INFO", f"🔄 {len(positions)} مركز مفتوح مزامَن")

            self.initialized = True
            self.add_log("INFO", "✅ البوت جاهز")
            return True
        except Exception as e:
            self.add_log("ERROR", f"❌ خطأ في التهيئة: {e}")
            return False

    def start_trading(self):
        if self.running:
            return False
        self.running = True
        self._stop_event.clear()
        self._bot_thread = threading.Thread(
            target=self._trading_loop, daemon=True, name="TradingLoop"
        )
        self._bot_thread.start()
        self.add_log("INFO", "🚀 التداول التلقائي بدأ")
        return True

    def stop_trading(self):
        self.running = False
        self._stop_event.set()
        self.add_log("INFO", "⏹️ التداول متوقف")

    def _trading_loop(self):
        cycle = 0
        while self.running and not self._stop_event.is_set():
            try:
                # ── فحص يوم العمل (الاثنين=0 .. الجمعة=4) ──
                today = datetime.now().weekday()
                if today >= 5:  # السبت=5، الأحد=6
                    day_name = "السبت" if today == 5 else "الأحد"
                    self.add_log("INFO", f"📅 اليوم {day_name} - عطلة نهاية الأسبوع، البوت في وضع السبات")
                    # نوم حتى منتصف الليل + ساعة إضافية
                    for _ in range(120):  # ~60 دقيقة
                        if self._stop_event.is_set():
                            return
                        time.sleep(30)
                    continue

                if not self.data_engine.is_market_open():
                    clock = self.data_engine.get_market_clock()
                    next_open = clock.get("next_open", "?")
                    self.add_log("INFO", f"💤 السوق مغلق - يفتح: {next_open}")
                    for _ in range(60):
                        if self._stop_event.is_set():
                            return
                        time.sleep(30)
                        if self.data_engine.is_market_open():
                            self.add_log("INFO", "🔔 السوق فتح!")
                            break
                    continue

                cycle += 1
                result = self.trading_engine.run_cycle()
                self.last_cycle = result

                if result.get("new_trades", 0) > 0:
                    self.add_log("INFO",
                        f"✅ دورة #{cycle} | {result['cycle_time_ms']}ms | "
                        f"صفقات جديدة: {result['new_trades']}")

                if self.guardian.check_circuit_breaker():
                    self.add_log("CRITICAL", "🚨 Circuit Breaker! إيقاف التداول")
                    self.running = False
                    break

                time.sleep(TRADING.data_refresh_seconds)

            except Exception as e:
                self.add_log("ERROR", f"❌ خطأ في الدورة: {e}")
                time.sleep(5)

    def get_uptime(self) -> str:
        """حساب مدة التشغيل"""
        if not hasattr(self, '_start_time'):
            self._start_time = datetime.now()
        delta = datetime.now() - self._start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"


state = BotState()
state._start_time = datetime.now()

# ── WebSocket Manager ─────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, data: dict):
        dead = set()
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        self.active -= dead


manager = ConnectionManager()


# ── Background Broadcaster ────────────────────────────────────
async def broadcaster():
    """يرسل تحديثات لحظية كل ثانية لجميع المتصلين"""
    prev_log_count = 0
    while True:
        try:
            if manager.active and state.initialized:
                payload = await build_snapshot()
                # أضف اللوقز الجديدة فقط
                new_logs = state.log_buffer[prev_log_count:]
                prev_log_count = len(state.log_buffer)
                payload["new_logs"] = new_logs
                await manager.broadcast(payload)
        except Exception as e:
            logger.error(f"Broadcaster error: {e}")
        await asyncio.sleep(1)


async def build_snapshot() -> dict:
    """بناء لقطة كاملة من البيانات"""
    try:
        # أسعار CIFR & IREN
        prices = {}
        if state.data_engine:
            quotes = state.data_engine.get_multi_quotes(TRADING.watchlist)
            for sym, q in quotes.items():
                last_trade = state.data_engine.get_latest_trade(sym)
                last_price = float(last_trade.get("price", 0) or 0)
                mid = float(q.get("mid", 0) or 0)
                bid = float(q.get("bid", 0) or 0)
                ask = float(q.get("ask", 0) or 0)

                display_price = 0.0
                price_source = "--"
                if last_price > 0:
                    display_price = last_price
                    price_source = "Last"
                elif mid > 0:
                    display_price = mid
                    price_source = "Mid"
                elif ask > 0:
                    display_price = ask
                    price_source = "Ask"
                elif bid > 0:
                    display_price = bid
                    price_source = "Bid"

                prices[sym] = {
                    "bid": round(bid, 4),
                    "ask": round(ask, 4),
                    "mid": round(mid, 4),
                    "last": round(last_price, 4),
                    "display_price": round(display_price, 4),
                    "price_source": price_source,
                    "spread_pct": round(q.get("spread_pct", 0), 3),
                }

        # Portfolio
        portfolio = {}
        if state.risk_manager:
            portfolio = state.risk_manager.get_portfolio_status()

        # Positions
        positions = []
        if state.data_engine:
            raw = state.data_engine.get_positions()
            for p in raw:
                pnl = p.get("unrealized_pl", 0)
                positions.append({
                    "symbol": p["symbol"],
                    "qty": p["quantity"],
                    "side": p["side"],
                    "entry": round(p["avg_entry_price"], 4),
                    "current": round(p["current_price"], 4),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(p.get("unrealized_plpc", 0) * 100, 2),
                    "change_today": round(p.get("change_today", 0) * 100, 2),
                })

        # Account
        account = {}
        if state.data_engine:
            acc = state.data_engine.get_account()
            account = {
                "equity": round(acc.get("equity", 0), 2),
                "cash": round(acc.get("cash", 0), 2),
                "buying_power": round(acc.get("buying_power", 0), 2),
                "day_trades": acc.get("day_trade_count", 0),
            }

        return {
            "type": "snapshot",
            "time": datetime.now().strftime("%H:%M:%S"),
            "bot_running": state.running,
            "market_open": state.data_engine.is_market_open() if state.data_engine else False,
            "prices": prices,
            "portfolio": portfolio,
            "positions": positions,
            "account": account,
            "last_cycle": state.last_cycle,
            "watchlist": TRADING.watchlist,
            "strategy": TRADING.strategy,
            "paper_trading": PAPER_TRADING,
            "settings": {
                "take_profit_pct": RISK.take_profit_pct,
                "stop_loss_pct": RISK.default_stop_loss_pct,
                "trailing_stop_pct": RISK.trailing_stop_pct
            }
        }
    except Exception as e:
        return {"type": "error", "message": str(e)}


# ── Startup ───────────────────────────────────────────────────


# ── Routes ─────────────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(_LOGIN_HTML.replace("{error}", ""))


@app.post("/login")
async def login_submit(password: str = Form(...)):
    if BOT_PASSWORD and password == BOT_PASSWORD:
        token = secrets.token_hex(32)
        valid_sessions.add(token)
        response = RedirectResponse("/", status_code=302)
        response.set_cookie("bot_session", token, httponly=True, secure=True,
                            samesite="lax", max_age=86400 * 30)
        return response
    error_html = '<p class="text-red-400 text-sm text-center mb-3">❌ كلمة المرور خاطئة</p>'
    return HTMLResponse(_LOGIN_HTML.replace("{error}", error_html), status_code=401)


@app.post("/logout")
async def logout(request: Request):
    token = request.cookies.get("bot_session")
    if token:
        valid_sessions.discard(token)
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("bot_session")
    return resp


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    token = ws.cookies.get("bot_session")
    if not _is_authenticated_token(token):
        await ws.close(code=4401)
        return

    await manager.connect(ws)
    # أرسل snapshot فورى عند الاتصال
    try:
        if state.initialized:
            snap = await build_snapshot()
            snap["logs"] = state.log_buffer[-50:]
            await ws.send_json(snap)
        async for _ in ws.iter_text():
            pass  # نستقبل أوامر من العميل هنا
    except WebSocketDisconnect:
        manager.disconnect(ws)
    finally:
        manager.disconnect(ws)


# ── API Endpoints ─────────────────────────────────────────────
@app.post("/api/start")
async def api_start():
    if not state.initialized:
        return {"ok": False, "msg": "البوت لم يتهيأ بعد"}
    ok = state.start_trading()
    return {"ok": ok, "msg": "التداول بدأ" if ok else "البوت يعمل بالفعل"}


@app.post("/api/stop")
async def api_stop():
    state.stop_trading()
    return {"ok": True, "msg": "التداول متوقف"}


@app.post("/api/scan")
async def api_scan():
    if not state.initialized:
        return {"ok": False, "signals": []}
    try:
        signals = state.trading_engine.scan_watchlist()
        result = []
        for s in signals:
            result.append({
                "symbol": s.symbol,
                "direction": s.direction,
                "strength": round(s.strength, 2),
                "confidence": round(s.confidence, 2),
                "entry": round(s.entry_price, 4),
                "stop_loss": round(s.stop_loss, 4),
                "take_profit": round(s.take_profit, 4),
                "reason": s.reason,
            })
        state.signals_buffer = result
        return {"ok": True, "signals": result}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

@app.post("/api/settings")
async def api_settings(request: Request):
    try:
        from config import RISK, save_dynamic_settings
        data = await request.json()
        if "take_profit" in data:
            RISK.take_profit_pct = float(data["take_profit"])
        if "stop_loss" in data:
            RISK.default_stop_loss_pct = float(data["stop_loss"])
        if "trailing" in data:
            RISK.trailing_stop_pct = float(data["trailing"])
            
        save_dynamic_settings()
        
        state.add_log("INFO", f"⚙️ تم تحديث النسب: ربح {RISK.take_profit_pct}% | خسارة {RISK.default_stop_loss_pct}% | تتبع {RISK.trailing_stop_pct}%")
        return {"ok": True, "msg": "تم حفظ الإعدادات"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


@app.post("/api/buy/{symbol}")
async def api_buy(symbol: str):
    if not state.initialized:
        return {"ok": False, "msg": "البوت لم يتهيأ"}
    result = state.trading_engine.quick_buy(symbol.upper())
    if "error" in result:
        return {"ok": False, "msg": result["error"]}
    state.add_log("INFO", f"🛒 شراء يدوي: {symbol} @ ${result.get('price', 0):.4f}")
    return {"ok": True, **result}


@app.post("/api/sell/{symbol}")
async def api_sell(symbol: str):
    if not state.initialized:
        return {"ok": False, "msg": "البوت لم يتهيأ"}
    result = state.trading_engine.quick_sell(symbol.upper())
    state.add_log("INFO", f"📤 بيع يدوي: {symbol}")
    return {"ok": True, **result}


@app.post("/api/emergency")
async def api_emergency():
    if not state.initialized:
        return {"ok": False}
    state.stop_trading()
    result = state.trading_engine.emergency_exit()
    state.add_log("CRITICAL", "🆘 خروج طارئ - تم إغلاق جميع الصفقات")
    return {"ok": True, **result}


@app.get("/api/status")
async def api_status():
    if not state.initialized:
        return {"initialized": False}
    return await build_snapshot()


@app.get("/health")
async def health_check():
    """Health check endpoint للمنصات السحابية (Railway, Render, etc.)"""
    return JSONResponse({
        "status": "healthy",
        "initialized": state.initialized,
        "bot_running": state.running,
        "uptime": state.get_uptime(),
        "auto_start": AUTO_START_TRADING,
        "paper_trading": PAPER_TRADING,
        "timestamp": datetime.now().isoformat(),
    })


@app.get("/api/auto-start")
async def api_auto_start_status():
    """حالة التشغيل التلقائي"""
    return {
        "auto_start": AUTO_START_TRADING,
        "auto_restart": AUTO_RESTART_ON_CRASH,
        "max_restarts": MAX_RESTART_ATTEMPTS,
    }


@app.post("/api/cancel-orders")
async def api_cancel_orders():
    """إلغاء جميع الأوامر المعلقة"""
    if not state.initialized:
        return {"ok": False, "msg": "البوت لم يتهيأ"}
    try:
        result = state.data_engine.cancel_all_orders()
        state.add_log("WARNING", "🚫 تم إلغاء جميع الأوامر المعلقة")
        return {"ok": True, "msg": "تم إلغاء جميع الأوامر"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


@app.post("/api/close/{symbol}")
async def api_close_position(symbol: str):
    """إغلاق مركز محدد"""
    if not state.initialized:
        return {"ok": False, "msg": "البوت لم يتهيأ"}
    try:
        result = state.data_engine.close_position(symbol.upper())
        if "error" in result:
            return {"ok": False, "msg": result["error"]}
        state.risk_manager.close_trade(symbol.upper(), 0, "manual_close")
        state.add_log("INFO", f"📝 إغلاق يدوي: {symbol.upper()}")
        return {"ok": True, "msg": f"تم إغلاق {symbol.upper()}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


@app.post("/api/close-all")
async def api_close_all():
    """إغلاق جميع المراكز بدون إيقاف البوت"""
    if not state.initialized:
        return {"ok": False, "msg": "البوت لم يتهيأ"}
    try:
        state.data_engine.close_all_positions()
        state.data_engine.cancel_all_orders()
        state.add_log("WARNING", "📝 تم إغلاق جميع المراكز والأوامر")
        return {"ok": True, "msg": "تم إغلاق الكل"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


@app.get("/api/orders")
async def api_get_orders():
    """جلب الأوامر المعلقة"""
    if not state.initialized:
        return {"ok": False, "orders": []}
    try:
        orders = state.data_engine.get_open_orders()
        return {"ok": True, "orders": orders}
    except Exception as e:
        return {"ok": False, "orders": [], "msg": str(e)}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(
        "web_app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )

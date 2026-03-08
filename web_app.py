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

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
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
                prices[sym] = {
                    "bid": round(q.get("bid", 0), 4),
                    "ask": round(q.get("ask", 0), 4),
                    "mid": round(q.get("mid", 0), 4),
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
        }
    except Exception as e:
        return {"type": "error", "message": str(e)}


# ── Startup ───────────────────────────────────────────────────


# ── Routes ─────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
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


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(
        "web_app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )

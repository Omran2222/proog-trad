"""
╔══════════════════════════════════════════════════════════════╗
║           Smart Scalper Bot Configuration - Alpaca API       ║
╚══════════════════════════════════════════════════════════════╝
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from dataclasses import dataclass, field
from typing import List

# ─── Alpaca API Keys ────────────────────────────────────────
# Put your keys here or use environment variables
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "YOUR_API_KEY_HERE")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "YOUR_SECRET_KEY_HERE")

# True = Paper Trading | False = Live Trading
PAPER_TRADING = True

# API URLs
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"
STREAM_URL = "wss://stream.data.alpaca.markets/v2/iex"

BASE_URL = PAPER_BASE_URL if PAPER_TRADING else LIVE_BASE_URL


@dataclass
class RiskConfig:
    """Risk Management Configuration - Weekly Trading Plan"""

    # ─── Loss Limits ─────────────────────────────────────
    max_loss_per_trade_pct: float = 2.0        # Max loss per trade (%)
    max_daily_loss_pct: float = 3.0            # Max daily loss (%)
    max_weekly_loss_pct: float = 5.0           # Max weekly loss (%)
    max_portfolio_drawdown_pct: float = 8.0    # Max portfolio drawdown (%)

    # ─── Position Sizing (Strict for CIFR / IREN) ─────────────
    max_position_size_pct: float = 2.0         # Max position size (1-2% max)
    max_total_exposure_pct: float = 50.0       # Max total exposure (%)
    max_positions: int = 2                     # Max open positions (CIFR & IREN only)
    
    # ─── Stop Loss / Take Profit (Weekly - Strict) ───────────
    default_stop_loss_pct: float = 8.0         # وقف خسارة 8% - CIFR/IREN تتحرك 10%+ يومياً
    trailing_stop_pct: float = 5.0             # تتبع أوسع لالتقاط حركات 20-30%
    take_profit_pct: float = 20.0              # أخذ أرباح عند 20% (المتداولون الناجحون يصبرون)

    # ─── Protection Filters ─────────────────────────────────────
    min_volume: int = 1_000_000                # Minimum volume
    min_price: float = 2.0                     # Minimum price (to accommodate IREN/CIFR)
    max_spread_pct: float = 1.0                # Max spread (%) 

    # ─── Timing Protection ─────────────────────────────────────
    avoid_first_minutes: int = 30              # CIFR/IREN عالية التذبذب في الـ 30 دقيقة الأولى
    avoid_last_minutes: int = 15               # Avoid last 15 minutes

    # ─── Emergency Stop ──────────────────────────────────────
    emergency_stop_loss_pct: float = 8.0       # Emergency stop per trade (%)
    circuit_breaker_loss_pct: float = 10.0     # Circuit breaker (%)


@dataclass
class TradingConfig:
    """Trading Configuration"""

    # ─── Strategies ───────────────────────────────────────
    strategy: str = "weekly_swing"             # استراتيجية المضارب الأسبوعي

    # ─── Watchlist ──────────────────────────────────
    watchlist: List[str] = field(default_factory=lambda: [
        "CIFR", "IREN"
    ])

    # ─── Technical Indicators (Weekly Swing) ──────────
    rsi_period: int = 14
    rsi_overbought: float = 70.0               # خروج عند التشبع القوي بدل الخروج المبكر جداً
    rsi_oversold: float = 32.0                 # دخول بعد ضغط بيعي أوضح

    ema_fast: int = 8                          
    ema_slow: int = 21
    ema_trend: int = 50

    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    bollinger_period: int = 20
    bollinger_std: float = 2.0

    vwap_enabled: bool = True

    # ─── Performance ───────────────────────────────────
    data_refresh_seconds: float = 30.0         # الأسبوعي لا يحتاج تحديث بالثانية
    order_timeout_seconds: int = 30            # وقت أطول للأوامر

    # ─── Signal Filters ───────────────────────────────────
    min_signal_strength: float = 0.72          # تقليل الإشارات الضعيفة في الأسهم المتذبذبة
    confirmation_candles: int = 2              # تأكيد كافٍ بدون تأخر كبير في الدخول


@dataclass
class NotificationConfig:
    """Notification Configuration"""
    log_trades: bool = True
    log_file: str = "trades_log.json"
    console_colors: bool = True
    show_portfolio_updates: bool = True
    alert_on_loss: bool = True


# ─── Default Configuration ──────────────────────────────
RISK = RiskConfig()
TRADING = TradingConfig()
NOTIFICATIONS = NotificationConfig()


def validate_config():
    """Validate Configuration"""
    errors = []
    
    if not ALPACA_API_KEY or ALPACA_API_KEY.startswith("YOUR_") or "XXX" in ALPACA_API_KEY:
        errors.append("⚠️  ALPACA_API_KEY must be set")
    if not ALPACA_SECRET_KEY or ALPACA_SECRET_KEY.startswith("YOUR_") or "XXX" in ALPACA_SECRET_KEY:
        errors.append("⚠️  ALPACA_SECRET_KEY must be set")
    
    if RISK.max_loss_per_trade_pct > 3.0:
        errors.append("⚠️  Max loss per trade is too high!")
    if RISK.max_position_size_pct > 15.0:
        errors.append("⚠️  Position size is too large!")
    if RISK.max_total_exposure_pct > 80.0:
        errors.append("⚠️  Total exposure is too high!")
    
    return errors


def print_config():
    """Print Current Configuration"""
    mode = "📝 Paper Trading" if PAPER_TRADING else "💰 Live Trading"
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    Current Bot Settings                      ║
╠══════════════════════════════════════════════════════════════╣
║  Mode: {mode:<52}║
║  Max Loss/Trade: {RISK.max_loss_per_trade_pct}%{'':<45}║
║  Max Daily Loss: {RISK.max_daily_loss_pct}%{'':<45}║
║  Stop Loss: {RISK.default_stop_loss_pct}%{'':<48}║
║  Trailing Stop: {RISK.trailing_stop_pct}%{'':<44}║
║  Take Profit: {RISK.take_profit_pct}%{'':<46}║
║  Max Positions: {RISK.max_positions}{'':<45}║
║  Strategy: {TRADING.strategy:<49}║
╚══════════════════════════════════════════════════════════════╝
""")

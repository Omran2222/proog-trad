"""
╔══════════════════════════════════════════════════════════════╗
║          Risk Management Engine - Zero Loss Guardian         ║
║         Risk Management Engine - Zero Loss Guardian          ║
╚══════════════════════════════════════════════════════════════╝

Main line of defense against loss.
Works on multiple levels:
  1. Pre-Entry Check
  2. In-Trade Monitoring
  3. Emergency Stop
  4. Circuit Breaker
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from config import RISK, TRADING

logger = logging.getLogger("RiskEngine")


@dataclass
class TradeRecord:
    """Trade Record"""
    symbol: str
    side: str  # buy / sell
    entry_price: float
    quantity: int
    entry_time: datetime
    stop_loss: float
    take_profit: float
    trailing_stop: float
    current_price: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: str = "open"  # open, closed, stopped


@dataclass
class DailyPnL:
    """Daily P&L"""
    date: str = ""
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_drawdown: float = 0.0
    circuit_breaker_triggered: bool = False


class RiskManager:
    """
    ═══════════════════════════════════════════════════════
    Risk Manager - Zero Loss Allowed
    ═══════════════════════════════════════════════════════
    """

    def __init__(self, account_equity: float):
        self.account_equity = account_equity
        self.initial_equity = account_equity
        self.peak_equity = account_equity
        
        self.open_trades: Dict[str, TradeRecord] = {}
        self.closed_trades: list = []
        self.daily_pnl = DailyPnL(date=datetime.now().strftime("%Y-%m-%d"))
        
        # System State
        self.trading_enabled = True
        self.circuit_breaker_active = False
        self.emergency_mode = False
        
        # Counters
        self.consecutive_losses = 0
        self.max_consecutive_losses = 3  # After 3 consecutive losses -> pause
        
        logger.info(f"🛡️ Risk Engine Ready | Equity: ${account_equity:,.2f}")

    # ══════════════════════════════════════════════════════
    # 1. Pre-Entry Check
    # ══════════════════════════════════════════════════════

    def can_open_trade(self, symbol: str, price: float, quantity: int,
                       side: str = "buy") -> Tuple[bool, str]:
        """
        Comprehensive check before opening any trade
        Returns (True, "") if allowed, or (False, "Reason")
        """
        
        # ─── Circuit Breaker Check ─────────────────────────────
        if self.circuit_breaker_active:
            return False, "🚨 Circuit Breaker Active - Trading Halted"
        
        if not self.trading_enabled:
            return False, "⛔ Trading Disabled"
        
        if self.emergency_mode:
            return False, "🆘 Emergency Mode Active"

        # ─── Consecutive Losses Check ────────────────────────
        if self.consecutive_losses >= self.max_consecutive_losses:
            return False, f"⚠️ {self.consecutive_losses} Consecutive Losses - Cooldown"

        # ─── Position Count Check ──────────────────────────────
        if len(self.open_trades) >= RISK.max_positions:
            return False, f"📊 Max Positions Reached: {RISK.max_positions}"

        # ─── Duplicate Trade Check ────────────────────────────
        if symbol in self.open_trades:
            return False, f"🔄 Position already open for {symbol}"

        # ─── Check Trade Size ───────────────────────────────
        trade_value = price * quantity
        max_trade_value = self.account_equity * (RISK.max_position_size_pct / 100)
        if trade_value > max_trade_value:
            return False, f"💰 Trade Size ${trade_value:,.0f} > Limit ${max_trade_value:,.0f}"

        # ─── Check Total Exposure ──────────────────────────
        current_exposure = self._calculate_total_exposure()
        new_exposure = current_exposure + trade_value
        max_exposure = self.account_equity * (RISK.max_total_exposure_pct / 100)
        if new_exposure > max_exposure:
            return False, f"📈 Total Exposure Exceeds Limit: ${new_exposure:,.0f} > ${max_exposure:,.0f}"

        # ─── Check Daily Loss ──────────────────────────
        if abs(self.daily_pnl.realized_pnl) > 0:
            daily_loss_pct = (self.daily_pnl.realized_pnl / self.initial_equity) * 100
            if daily_loss_pct <= -RISK.max_daily_loss_pct:
                self._trigger_circuit_breaker("Daily Loss Limit Exceeded")
                return False, f"📉 Daily Loss {daily_loss_pct:.1f}% Exceeded Limit"

        # ─── Check Minimum Price ─────────────────────────────
        if price < RISK.min_price:
            return False, f"💲 Price ${price} < Low Price Limit ${RISK.min_price}"

        # ─── Check Safe Trading Time ─────────────────────────────
        time_check = self._check_safe_trading_time()
        if not time_check[0]:
            return False, time_check[1]

        return True, "✅ Trading Allowed"

    # ══════════════════════════════════════════════════════
    # 2. Calculate Protection Levels
    # ══════════════════════════════════════════════════════

    def calculate_position_size(self, price: float, stop_loss_price: float) -> int:
        """
        Calculate optimal position size based on risk
        Rule: Do not risk more than X% of equity in a single trade
        """
        if stop_loss_price >= price:
            return 0
        
        risk_per_share = price - stop_loss_price
        max_risk_amount = self.account_equity * (RISK.max_loss_per_trade_pct / 100)
        
        optimal_size = int(max_risk_amount / risk_per_share)
        
        # Check position size limit
        max_by_position = int(
            (self.account_equity * RISK.max_position_size_pct / 100) / price
        )
        
        return min(optimal_size, max_by_position, max(1, optimal_size))

    def calculate_stop_levels(self, price: float, side: str = "buy") -> Dict[str, float]:
        """Calculate all protection levels"""
        # Normalize side (buy/long -> buy, sell/short -> sell)
        normalized_side = "buy" if side.lower() in ["buy", "long"] else "sell"

        if normalized_side == "buy":
            stop_loss = price * (1 - RISK.default_stop_loss_pct / 100)
            trailing_stop = price * (1 - RISK.trailing_stop_pct / 100)
            take_profit = price * (1 + RISK.take_profit_pct / 100)
            emergency_stop = price * (1 - RISK.emergency_stop_loss_pct / 100)
        else:
            stop_loss = price * (1 + RISK.default_stop_loss_pct / 100)
            trailing_stop = price * (1 + RISK.trailing_stop_pct / 100)
            take_profit = price * (1 - RISK.take_profit_pct / 100)
            emergency_stop = price * (1 + RISK.emergency_stop_loss_pct / 100)

        return {
            "stop_loss": round(stop_loss, 2),
            "trailing_stop": round(trailing_stop, 2),
            "take_profit": round(take_profit, 2),
            "emergency_stop": round(emergency_stop, 2)
        }

    # ══════════════════════════════════════════════════════
    # 3. Monitor Open Trades
    # ══════════════════════════════════════════════════════

    def register_trade(self, symbol: str, side: str, price: float,
                       quantity: int) -> TradeRecord:
        """Register new trade"""
        # Normalize side
        normalized_side = "buy" if side.lower() in ["buy", "long"] else "sell"
        
        levels = self.calculate_stop_levels(price, normalized_side)
        
        trade = TradeRecord(
            symbol=symbol,
            side=normalized_side,
            entry_price=price,
            quantity=quantity,
            entry_time=datetime.now(),
            stop_loss=levels["stop_loss"],
            take_profit=levels["take_profit"],
            trailing_stop=levels["trailing_stop"],
            current_price=price,
        )
        
        self.open_trades[symbol] = trade
        self.daily_pnl.total_trades += 1
        
        logger.info(
            f"📝 New Trade: {normalized_side.upper()} {quantity}x {symbol} @ ${price:.2f} | "
            f"SL: ${levels['stop_loss']:.2f} | TP: ${levels['take_profit']:.2f}"
        )
        
        return trade

    def update_trade(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Update trade and check protection levels
        Returns required action: None, "close_profit", "close_loss", "emergency_close"
        """
        if symbol not in self.open_trades:
            return None
        
        trade = self.open_trades[symbol]
        trade.current_price = current_price
        
        # Calculate PnL
        if trade.side == "buy":
            trade.pnl = (current_price - trade.entry_price) * trade.quantity
            trade.pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        else:
            trade.pnl = (trade.entry_price - current_price) * trade.quantity
            trade.pnl_pct = ((trade.entry_price - current_price) / trade.entry_price) * 100

        # ─── Emergency Stop Check ──────────────────────
        if trade.side == "buy" and current_price <= trade.stop_loss * (1 - RISK.emergency_stop_loss_pct / 100 / 2):
            logger.critical(f"🆘 Emergency Stop: {symbol} @ ${current_price:.2f}")
            return "emergency_close"
        if trade.side == "sell" and current_price >= trade.stop_loss * (1 + RISK.emergency_stop_loss_pct / 100 / 2):
            logger.critical(f"🆘 Emergency Stop: {symbol} @ ${current_price:.2f}")
            return "emergency_close"

        # ─── Stop Loss Check ──────────────────────────────
        if trade.side == "buy" and current_price <= trade.stop_loss:
            logger.warning(f"🛑 Stop Loss: {symbol} @ ${current_price:.2f} (Loss: {trade.pnl_pct:.1f}%)")
            return "close_loss"
        if trade.side == "sell" and current_price >= trade.stop_loss:
            logger.warning(f"🛑 Stop Loss: {symbol} @ ${current_price:.2f} (Loss: {trade.pnl_pct:.1f}%)")
            return "close_loss"

        # ─── Take Profit Check ─────────────────────────────
        if trade.side == "buy" and current_price >= trade.take_profit:
            logger.info(f"🎯 Take Profit: {symbol} @ ${current_price:.2f} (Profit: {trade.pnl_pct:.1f}%)")
            return "close_profit"
        if trade.side == "sell" and current_price <= trade.take_profit:
            logger.info(f"🎯 Take Profit: {symbol} @ ${current_price:.2f} (Profit: {trade.pnl_pct:.1f}%)")
            return "close_profit"

        # ─── Update Trailing Stop ─────────────────────────
        self._update_trailing_stop(trade, current_price)

        return None

    def close_trade(self, symbol: str, close_price: float, reason: str = "") -> Optional[TradeRecord]:
        """Close trade and record it"""
        if symbol not in self.open_trades:
            return None
        
        trade = self.open_trades.pop(symbol)
        trade.status = "closed"
        trade.current_price = close_price
        
        # حساب الربح النهائي
        if trade.side == "buy":
            trade.pnl = (close_price - trade.entry_price) * trade.quantity
        else:
            trade.pnl = (trade.entry_price - close_price) * trade.quantity
        
        trade.pnl_pct = (trade.pnl / (trade.entry_price * trade.quantity)) * 100
        
        # Update Stats
        self.daily_pnl.realized_pnl += trade.pnl
        self.account_equity += trade.pnl
        
        if trade.pnl >= 0:
            self.daily_pnl.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.daily_pnl.losing_trades += 1
            self.consecutive_losses += 1
        
        # Update Peak
        if self.account_equity > self.peak_equity:
            self.peak_equity = self.account_equity
        
        # Check Drawdown
        drawdown = ((self.peak_equity - self.account_equity) / self.peak_equity) * 100
        if drawdown > self.daily_pnl.max_drawdown:
            self.daily_pnl.max_drawdown = drawdown
        
        # Check Circuit Breaker
        if drawdown >= RISK.circuit_breaker_loss_pct:
            self._trigger_circuit_breaker(f"Portfolio Drawdown {drawdown:.1f}%")
        
        self.closed_trades.append(trade)
        
        emoji = "💚" if trade.pnl >= 0 else "🔴"
        logger.info(
            f"{emoji} Closed {symbol}: ${trade.pnl:+,.2f} ({trade.pnl_pct:+.1f}%) | "
            f"Reason: {reason} | Balance: ${self.account_equity:,.2f}"
        )
        
        return trade

    # ══════════════════════════════════════════════════════
    # 4. Advanced Protection Systems
    # ══════════════════════════════════════════════════════

    def _update_trailing_stop(self, trade: TradeRecord, current_price: float):
        """Update Trailing Stop - To Protect Profits"""
        if trade.side == "buy":
            new_trailing = current_price * (1 - RISK.trailing_stop_pct / 100)
            if new_trailing > trade.trailing_stop:
                old_stop = trade.trailing_stop
                trade.trailing_stop = new_trailing
                # Rise Stop Loss with Trailing Stop
                if new_trailing > trade.stop_loss:
                    trade.stop_loss = new_trailing
                    logger.info(
                        f"📈 Trailing Stop {trade.symbol}: "
                        f"${old_stop:.2f} → ${new_trailing:.2f}"
                    )
        else:
            new_trailing = current_price * (1 + RISK.trailing_stop_pct / 100)
            if new_trailing < trade.trailing_stop:
                old_stop = trade.trailing_stop
                trade.trailing_stop = new_trailing
                if new_trailing < trade.stop_loss:
                    trade.stop_loss = new_trailing
                    logger.info(
                        f"📉 Trailing Stop {trade.symbol}: "
                        f"${old_stop:.2f} → ${new_trailing:.2f}"
                    )

    def _trigger_circuit_breaker(self, reason: str):
        """Trigger Circuit Breaker - Full Trading Halt"""
        self.circuit_breaker_active = True
        self.trading_enabled = False
        self.daily_pnl.circuit_breaker_triggered = True
        logger.critical(f"🚨🚨🚨 Circuit Breaker Triggered: {reason}")
        logger.critical("⛔ All trading operations halted pending review")

    def emergency_close_all(self) -> list:
        """Close All Trades Immediately - Emergency Mode"""
        self.emergency_mode = True
        closed = []
        for symbol in list(self.open_trades.keys()):
            trade = self.open_trades[symbol]
            result = self.close_trade(symbol, trade.current_price, "Emergency Close")
            if result:
                closed.append(result)
        
        logger.critical(f"🆘 Emergency Close: {len(closed)} trades")
        return closed

    def _calculate_total_exposure(self) -> float:
        """Calculate Total Current Exposure"""
        return sum(
            t.current_price * t.quantity 
            for t in self.open_trades.values()
        )

    def _check_safe_trading_time(self) -> Tuple[bool, str]:
        """Check if Time is Safe for Trading"""
        now = datetime.now()
        
        # New York Market Hours (EST): 9:30 AM - 4:00 PM
        # Note: This simple logic assumes bot runs in EST timezone or adjust accordingly
        market_open = now.replace(hour=9, minute=30, second=0)
        market_close = now.replace(hour=16, minute=0, second=0)
        
        avoid_start = market_open + timedelta(minutes=RISK.avoid_first_minutes)
        avoid_end = market_close - timedelta(minutes=RISK.avoid_last_minutes)
        
        if now < avoid_start:
            return False, f"⏰ Wait {RISK.avoid_first_minutes} min after open"
        if now > avoid_end:
            return False, f"⏰ Last {RISK.avoid_last_minutes} min before close"
        
        return True, ""

    # ══════════════════════════════════════════════════════
    # 5. Reports & Stats
    # ══════════════════════════════════════════════════════

    def get_portfolio_status(self) -> Dict:
        """Overall Portfolio Status"""
        unrealized = sum(t.pnl for t in self.open_trades.values())
        total_pnl = self.daily_pnl.realized_pnl + unrealized
        total_pnl_pct = (total_pnl / self.initial_equity) * 100 if self.initial_equity > 0 else 0
        
        drawdown = ((self.peak_equity - self.account_equity) / self.peak_equity) * 100 \
            if self.peak_equity > 0 else 0
        
        win_rate = 0
        if self.daily_pnl.total_trades > 0:
            total_closed = self.daily_pnl.winning_trades + self.daily_pnl.losing_trades
            if total_closed > 0:
                win_rate = (self.daily_pnl.winning_trades / total_closed) * 100

        return {
            "equity": self.account_equity,
            "initial_equity": self.initial_equity,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "realized_pnl": self.daily_pnl.realized_pnl,
            "unrealized_pnl": unrealized,
            "open_positions": len(self.open_trades),
            "total_trades": self.daily_pnl.total_trades,
            "win_rate": win_rate,
            "max_drawdown": drawdown,
            "exposure": self._calculate_total_exposure(),
            "trading_enabled": self.trading_enabled,
            "circuit_breaker": self.circuit_breaker_active,
            "consecutive_losses": self.consecutive_losses
        }

    def print_status(self):
        """Print Portfolio Status"""
        s = self.get_portfolio_status()
        pnl_emoji = "💚" if s["total_pnl"] >= 0 else "🔴"
        
        print(f"""
╔══════════════════════════════════════════════════════════════╗
║                     📊 Portfolio Status                      ║
╠══════════════════════════════════════════════════════════════╣
║  💰 Equity: ${s['equity']:>12,.2f}                            ║
║  {pnl_emoji} PnL: ${s['total_pnl']:>+10,.2f} ({s['total_pnl_pct']:>+.1f}%)                 ║
║  📈 Open Trades: {s['open_positions']:>3}                                     ║
║  🎯 Win Rate: {s['win_rate']:>5.1f}%                                     ║
║  📉 Max Drawdown: {s['max_drawdown']:>5.1f}%                                ║
║  🔄 Cons. Losses: {s['consecutive_losses']:>2}                                     ║
║  {'🟢 Trading Active' if s['trading_enabled'] else '🔴 Trading Halted':<52}║
╚══════════════════════════════════════════════════════════════╝
""")

    def reset_daily(self):
        """Reset Daily Stats"""
        self.daily_pnl = DailyPnL(date=datetime.now().strftime("%Y-%m-%d"))
        self.initial_equity = self.account_equity
        self.consecutive_losses = 0
        
        # Re-enable trading if no major drawdown
        drawdown = ((self.peak_equity - self.account_equity) / self.peak_equity) * 100
        if drawdown < RISK.max_portfolio_drawdown_pct:
            self.circuit_breaker_active = False
            self.trading_enabled = True
            self.emergency_mode = False
            logger.info("🔄 إعادة تعيين يومية - التداول مفعل")
        else:
            logger.warning(f"⚠️ التراجع الكلي {drawdown:.1f}% - التداول يبقى معطل")

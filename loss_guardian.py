"""
╔══════════════════════════════════════════════════════════════╗
║         Loss Guardian Shield - Ultimate Portfolio Safety     ║
╚══════════════════════════════════════════════════════════════╝

Multi-layer protection system:

  Layer 1: Pre-Entry Filter
  Layer 2: Bracket Orders (Auto Stop + TP)
  Layer 3: Trailing Stop
  Layer 4: Continuous Monitoring + Instant Close
  Layer 5: Circuit Breaker
  Layer 6: Emergency Stop
  Layer 7: Daily/Weekly Loss Limit
"""

import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
from config import RISK, TRADING

logger = logging.getLogger("LossGuardian")


class LossGuardian:
    """
    ═══════════════════════════════════════════════════════
    Loss Guardian - 7 Protection Layers
    ═══════════════════════════════════════════════════════
    
    Runs independently from trading engine.
    If engine fails, Guardian protects portfolio.
    """

    def __init__(self, data_engine, risk_manager):
        self.data = data_engine
        self.risk = risk_manager
        
        # Protection Log
        self.protection_log: List[dict] = []
        self.daily_stats = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "interventions": 0,
            "losses_prevented": 0.0,
            "emergency_stops": 0,
            "circuit_breakers": 0,
        }
        
        # Guardian State
        self.guardian_active = True
        self.last_check = time.time()
        self.check_interval = 0.5  # Check every 0.5s
        
        # Load History
        self._load_history()
        
        logger.info("🛡️🛡️🛡️ Loss Guardian Active - 7 Protection Layers")

    # ══════════════════════════════════════════════════════
    # Layer 1: Pre-Entry Filter
    # ══════════════════════════════════════════════════════

    def pre_entry_filter(self, symbol: str, price: float,
                         qty: int, side: str) -> Dict:
        """
        Comprehensive pre-entry filter
        More strict than risk management check
        """
        checks = {
            "passed": True,
            "checks": [],
            "warnings": [],
            "blocked": False
        }

        # 1. Market Status Check
        if not self.data.is_market_open():
            checks["passed"] = False
            checks["checks"].append("❌ Market Closed")
            checks["blocked"] = True
            return checks

        # 2. Volume Check
        try:
            snapshot = self.data.get_snapshot(symbol)
            daily_vol = snapshot.get("daily_bar", {}).get("volume", 0)
            if daily_vol < RISK.min_volume:
                checks["passed"] = False
                checks["checks"].append(f"❌ Low Volume: {daily_vol:,}")
        except:
            checks["warnings"].append("⚠️ Failed to check volume")

        # 3. Spread Check
        quote = self.data.get_latest_quote(symbol)
        spread_pct = quote.get("spread_pct", 0)
        if spread_pct > RISK.max_spread_pct:
            checks["passed"] = False
            checks["checks"].append(f"❌ High Spread: {spread_pct:.2f}%")

        # 4. Excessive volatility check
        bars = self.data.get_intraday_bars(symbol, minutes=5, limit=12)
        if bars and len(bars) >= 2:
            recent_range = max(b["high"] for b in bars[-6:]) - min(b["low"] for b in bars[-6:])
            range_pct = (recent_range / price) * 100
            if range_pct > 5:
                checks["warnings"].append(f"⚠️ High Volatility: {range_pct:.1f}%")
                if range_pct > 10:
                    checks["passed"] = False
                    checks["checks"].append(f"❌ Dangerous Volatility: {range_pct:.1f}%")

        # 5. Risk/Reward ratio check
        trade_value = price * qty
        max_risk = self.risk.account_equity * (RISK.max_loss_per_trade_pct / 100)
        if trade_value * (RISK.default_stop_loss_pct / 100) > max_risk:
            checks["passed"] = False
            checks["checks"].append("❌ Risk exceeds allowed limit")

        # 6. Daily trade count check
        if self.daily_stats["interventions"] >= 5:
            checks["warnings"].append("⚠️ High number of guardian interventions today")

        # 7. Consecutive losses check
        if self.risk.consecutive_losses >= 2:
            checks["warnings"].append(f"⚠️ {self.risk.consecutive_losses} consecutive losses")
            if self.risk.consecutive_losses >= 3:
                checks["passed"] = False
                checks["checks"].append("❌ 3+ Consecutive losses - Cooldown required")

        checks["checks"].append("✅ Guardian check passed" if checks["passed"] else "⛔ Rejected by Guardian")
        
        if not checks["passed"]:
            self._log_intervention("pre_entry_filter", symbol, 
                                   f"Entry rejected: {'; '.join(checks['checks'])}")
        
        return checks

    # ══════════════════════════════════════════════════════
    # Layer 2 & 3: In-trade Protection
    # ══════════════════════════════════════════════════════

    def guard_positions(self) -> List[dict]:
        """
        Monitor all open positions
        Runs in parallel with trading engine as a safety net
        """
        actions = []
        
        for symbol, trade in list(self.risk.open_trades.items()):
            try:
                price = self.data.get_live_price(symbol)
                if price <= 0:
                    continue
                
                # ─── Sharp Loss Check ───────────────────
                if trade.side == "buy":
                    loss_pct = ((price - trade.entry_price) / trade.entry_price) * 100
                else:
                    loss_pct = ((trade.entry_price - price) / trade.entry_price) * 100
                
                # Guardian level emergency stop
                if loss_pct <= -RISK.emergency_stop_loss_pct:
                    actions.append({
                        "action": "EMERGENCY_CLOSE",
                        "symbol": symbol,
                        "price": price,
                        "loss_pct": loss_pct,
                        "reason": f"Severe loss {loss_pct:.1f}%"
                    })
                    self._emergency_close(symbol, price, 
                                          f"Severe loss {loss_pct:.1f}%")
                    continue
                
                # ─── Rapid Drop Check ───────────────────
                bars = self.data.get_intraday_bars(symbol, minutes=1, limit=5)
                if bars and len(bars) >= 3:
                    rapid_drop = self._detect_rapid_movement(bars, trade.side)
                    if rapid_drop:
                        actions.append({
                            "action": "RAPID_DROP_CLOSE",
                            "symbol": symbol,
                            "price": price,
                            "reason": "Sudden sharp drop"
                        })
                        self._emergency_close(symbol, price, "Sudden sharp drop")
                        continue
                
                # ─── Profit Protection ────────────────────────
                if loss_pct > 1.0:  # If profit > 1%
                    # Adjust stop loss to secure profit
                    new_stop = self._calculate_profit_protection_stop(
                        trade.side, trade.entry_price, price, loss_pct
                    )
                    if new_stop and new_stop != trade.stop_loss:
                        old_stop = trade.stop_loss
                        trade.stop_loss = new_stop
                        actions.append({
                            "action": "PROFIT_PROTECT",
                            "symbol": symbol,
                            "old_stop": old_stop,
                            "new_stop": new_stop,
                            "profit_pct": loss_pct
                        })
                        logger.info(
                            f"🔒 Protecting profit {symbol}: Stop "
                            f"${old_stop:.2f} → ${new_stop:.2f} "
                            f"(Profit: {loss_pct:.1f}%)"
                        )
                
            except Exception as e:
                logger.error(f"❌ Error monitoring {symbol}: {e}")
        
        return actions

    # ══════════════════════════════════════════════════════
    # Layer 4: Detect Sudden Movements
    # ══════════════════════════════════════════════════════

    def _detect_rapid_movement(self, bars: List[dict], side: str) -> bool:
        """Detect sudden rapid drop/rise"""
        if len(bars) < 3:
            return False
        
        # Check last 3 candles
        changes = []
        for i in range(1, len(bars)):
            change = ((bars[i]["close"] - bars[i-1]["close"]) / bars[i-1]["close"]) * 100
            changes.append(change)
        
        if side == "buy":
            # Rapid drop against buy
            total_drop = sum(c for c in changes[-3:] if c < 0)
            if total_drop < -2.0:  # More than 2% in 3 minutes
                return True
        else:
            # Rapid rise against sell
            total_rise = sum(c for c in changes[-3:] if c > 0)
            if total_rise > 2.0:
                return True
        
        return False

    def _calculate_profit_protection_stop(self, side: str, entry: float,
                                           current: float,
                                           profit_pct: float) -> Optional[float]:
        """Calculate profit protection stop"""
        if profit_pct < 1.0:
            return None
        
        if side == "buy":
            if profit_pct >= 2.0:
                # Profit 2%+ → Stop at Breakeven + 0.5%
                return round(entry * 1.005, 2)
            elif profit_pct >= 1.5:
                # Profit 1.5%+ → Stop at Breakeven
                return round(entry, 2)
            elif profit_pct >= 1.0:
                # Profit 1%+ → Closer Stop
                return round(entry * 0.998, 2)
        else:
            if profit_pct >= 2.0:
                return round(entry * 0.995, 2)
            elif profit_pct >= 1.5:
                return round(entry, 2)
            elif profit_pct >= 1.0:
                return round(entry * 1.002, 2)
        
        return None

    # ══════════════════════════════════════════════════════
    # Layer 5: Circuit Breaker
    # ══════════════════════════════════════════════════════

    def check_circuit_breaker(self) -> bool:
        """Comprehensive circuit breaker check"""
        portfolio = self.risk.get_portfolio_status()
        
        # Daily loss
        if portfolio["total_pnl_pct"] <= -RISK.max_daily_loss_pct:
            self._trigger_full_stop(
                f"Daily loss {portfolio['total_pnl_pct']:.1f}% "
                f"exceeded limit {RISK.max_daily_loss_pct}%"
            )
            return True
        
        # Portfolio drawdown
        if portfolio["max_drawdown"] >= RISK.max_portfolio_drawdown_pct:
            self._trigger_full_stop(
                f"Portfolio drawdown {portfolio['max_drawdown']:.1f}% "
                f"exceeded limit {RISK.max_portfolio_drawdown_pct}%"
            )
            return True
        
        # Early warning
        if portfolio["total_pnl_pct"] <= -(RISK.max_daily_loss_pct * 0.7):
            logger.warning(
                f"⚠️ Early Warning: Loss {portfolio['total_pnl_pct']:.1f}% "
                f"approaching limit"
            )
        
        return False

    # ══════════════════════════════════════════════════════
    # Layer 6: Emergency Stop
    # ══════════════════════════════════════════════════════

    def _emergency_close(self, symbol: str, price: float, reason: str):
        """Emergency close for a single position"""
        logger.critical(f"🆘 Emergency Close: {symbol} @ ${price:.2f} | {reason}")
        
        # Close via Alpaca
        self.data.close_position(symbol)
        
        # Close in risk management
        self.risk.close_trade(symbol, price, f"Guardian: {reason}")
        
        self.daily_stats["emergency_stops"] += 1
        self.daily_stats["interventions"] += 1
        
        self._log_intervention("emergency_close", symbol, reason)

    def _trigger_full_stop(self, reason: str):
        """Full trading stop"""
        logger.critical(f"🚨🚨🚨 Full Stop: {reason}")
        
        # Cancel all orders
        self.data.cancel_all_orders()
        
        # Close all positions
        self.data.close_all_positions()
        
        # Close in risk management
        self.risk.emergency_close_all()
        
        self.daily_stats["circuit_breakers"] += 1
        self.daily_stats["interventions"] += 1
        
        self._log_intervention("full_stop", "ALL", reason)

    # ══════════════════════════════════════════════════════
    # Layer 7: Reports and Logs
    # ══════════════════════════════════════════════════════

    def _log_intervention(self, intervention_type: str, symbol: str, reason: str):
        """Log guardian intervention"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": intervention_type,
            "symbol": symbol,
            "reason": reason,
            "portfolio_equity": self.risk.account_equity,
        }
        self.protection_log.append(entry)
        self._save_history()

    def _save_history(self):
        """Save protection log"""
        try:
            log_file = Path("guardian_log.json")
            data = {
                "last_updated": datetime.now().isoformat(),
                "daily_stats": self.daily_stats,
                "interventions": self.protection_log[-100:]  # Last 100
            }
            log_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.error(f"❌ Error saving log: {e}")

    def _load_history(self):
        """Load protection log"""
        try:
            log_file = Path("guardian_log.json")
            if log_file.exists():
                data = json.loads(log_file.read_text())
                # Load only if same day
                if data.get("daily_stats", {}).get("date") == datetime.now().strftime("%Y-%m-%d"):
                    self.daily_stats = data["daily_stats"]
                    self.protection_log = data.get("interventions", [])
                    logger.info(f"📂 Protection log loaded: {len(self.protection_log)} interventions")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load log: {e}")

    def get_guardian_status(self) -> Dict:
        """Guardian status"""
        return {
            "active": self.guardian_active,
            "daily_interventions": self.daily_stats["interventions"],
            "emergency_stops": self.daily_stats["emergency_stops"],
            "circuit_breakers": self.daily_stats["circuit_breakers"],
            "losses_prevented": self.daily_stats["losses_prevented"],
            "protection_layers": 7,
            "check_interval_ms": int(self.check_interval * 1000),
        }

    def print_guardian_status(self):
        """Print Guardian Status"""
        s = self.get_guardian_status()
        print(f"""
╔══════════════════════════════════════════════════════════════╗
║                   🛡️ Loss Guardian Status                   ║
╠══════════════════════════════════════════════════════════════╣
║  Status: {'🟢 Active' if s['active'] else '🔴 Inactive':<53}║
║  Protection Layers: {s['protection_layers']} layers{'':<38}║
║  Check Interval: {s['check_interval_ms']} ms{'':<38}║
║  Today's Interventions: {s['daily_interventions']}{'':<46}║
║  Emergency Stops: {s['emergency_stops']}{'':<47}║
║  Circuit Breaker: {s['circuit_breakers']}{'':<47}║
╚══════════════════════════════════════════════════════════════╝
""")

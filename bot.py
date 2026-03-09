#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║            🤖 Smart Scalper Bot - Alpaca API Trading         ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Features:                                                   ║
║  ✅ Fastest order execution (< 100ms)                        ║
║  ✅ Accurate market data (REST + WebSocket)                  ║
║  ✅ 7 Layers of Loss Protection                              ║
║  ✅ Zero Loss Guardian                                       ║
║  ✅ Automatic Bracket Orders                                 ║
║  ✅ Smart Trailing Stop                                      ║
║  ✅ Circuit Breaker                                          ║
║  ✅ Technical Analysis (7 Indicators)                        ║
║  ✅ 3 Trading Strategies                                     ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""

import sys
import time
import signal
import logging
import threading
from datetime import datetime

from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY, PAPER_TRADING,
    RISK, TRADING, validate_config, print_config
)
from data_engine import AlpacaDataEngine
from risk_manager import RiskManager
from technical_analysis import TechnicalAnalyzer
from trading_engine import SmartTradingEngine
from loss_guardian import LossGuardian


# ══════════════════════════════════════════════════════════════
# إعداد التسجيل
# Logging Setup
# ══════════════════════════════════════════════════════════════

def setup_logging():
    """Setup logging system"""
    log_format = "%(asctime)s │ %(name)-15s │ %(levelname)-8s │ %(message)s"
    date_format = "%H:%M:%S"
    
    # Log file
    file_handler = logging.FileHandler(
        f"bot_{datetime.now().strftime('%Y%m%d')}.log",
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # Console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, console_handler]
    )


# ══════════════════════════════════════════════════════════════
# Main Bot
# ══════════════════════════════════════════════════════════════

class SmartScalperBot:
    """
    ═══════════════════════════════════════════════════════
    Main Bot - Connects all engines
    ═══════════════════════════════════════════════════════
    """

    def __init__(self):
        self.logger = logging.getLogger("Bot")
        self.running = False
        self._stop_event = threading.Event()
        
        # Check Config
        errors = validate_config()
        critical_error = False
        if errors:
            for err in errors:
                self.logger.warning(err)
                if "must be set" in err:
                    critical_error = True
            
            if critical_error:
                self.logger.error("⛔ Bot stopped due to missing critical data (API Keys)")
                sys.exit(1)

        self.logger.info("🤖 Initializing Bot...")

        # ─── Initialize Engines ────────────────────────────────
        self.data_engine = AlpacaDataEngine()
        
        # Get Account Data
        account = self.data_engine.get_account()
        if not account:
            self.logger.error("❌ Failed to connect to Alpaca API")
            self.logger.error("   Check API keys in config.py")
            sys.exit(1)
        
        equity = account.get("equity", 0)
        self.logger.info(f"💰 Equity: ${equity:,.2f}")
        
        self.risk_manager = RiskManager(equity)
        self.analyzer = TechnicalAnalyzer()
        self.trading_engine = SmartTradingEngine(
            self.data_engine, self.risk_manager, self.analyzer
        )
        self.guardian = LossGuardian(self.data_engine, self.risk_manager)
        
        # Sync Open Positions
        self._sync_positions()
        
        self.logger.info("✅ Bot is ready")

    def _sync_positions(self):
        """Sync open positions from Alpaca"""
        positions = self.data_engine.get_positions()
        for pos in positions:
            self.risk_manager.register_trade(
                pos["symbol"],
                pos["side"],
                pos["avg_entry_price"],
                pos["quantity"]
            )
        if positions:
            self.logger.info(f"🔄 Synced {len(positions)} open positions")
    # ══════════════════════════════════════════════════════
    # Main Loop
    # ══════════════════════════════════════════════════════

    def start(self):
        """Start Bot"""
        self.running = True
        
        print_config()
        self.risk_manager.print_status()
        self.guardian.print_guardian_status()
        
        self.logger.info("🚀 Bot is running now!")
        self.logger.info(f"📋 Strategy: {TRADING.strategy}")
        self.logger.info(f"👁️ Watchlist: {', '.join(TRADING.watchlist)}")
        self.logger.info("─" * 60)
        
        # Signal registration (main thread only)
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except ValueError:
            pass  # Not main thread (interactive mode)
        
        # Start Guardian Thread
        guardian_thread = threading.Thread(
            target=self._guardian_loop,
            daemon=True,
            name="LossGuardian"
        )
        guardian_thread.start()
        
        # Main Loop
        cycle = 0
        while self.running and not self._stop_event.is_set():
            try:
                cycle += 1
                
                # ── فحص يوم العمل (الاثنين=0 .. الجمعة=4) ──
                from datetime import datetime as _dt
                today = _dt.now().weekday()
                if today >= 5:  # السبت أو الأحد
                    day_name = "السبت" if today == 5 else "الأحد"
                    self.logger.info(f"📅 اليوم {day_name} - عطلة نهاية الأسبوع، البوت في وضع السبات")
                    for _ in range(120):  # ~60 دقيقة
                        if self._stop_event.is_set():
                            return
                        time.sleep(30)
                    continue

                # Check Market Status
                if not self.data_engine.is_market_open():
                    self.logger.info("💤 Market Closed - Waiting...")
                    self._wait_for_market()
                    continue
                
                # Run Trading Cycle
                result = self.trading_engine.run_cycle()
                
                # Print Summary every 10 cycles
                if cycle % 10 == 0:
                    self._print_cycle_summary(cycle, result)
                
                # Check Circuit Breaker
                if self.guardian.check_circuit_breaker():
                    self.logger.critical("🚨 Circuit Breaker Triggered! Stopping Trading")
                    self.running = False
                    break
                
                # Wait before next cycle
                time.sleep(TRADING.data_refresh_seconds)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"❌ Error in cycle {cycle}: {e}")
                time.sleep(5)  # Wait 5 seconds after error
        
        self._shutdown()

    def _guardian_loop(self):
        """Loss Guardian Loop - Runs independently"""
        self.logger.info("🛡️ Guardian Thread Started")
        
        while self.running and not self._stop_event.is_set():
            try:
                self.guardian.guard_positions()
                time.sleep(self.guardian.check_interval)
            except Exception as e:
                self.logger.error(f"❌ Guardian Error: {e}")
                time.sleep(1)

    def _wait_for_market(self):
        """Wait for market open"""
        clock = self.data_engine.get_market_clock()
        next_open = clock.get("next_open", "Unknown")
        self.logger.info(f"⏰ Market Opens: {next_open}")
        
        # Check every 30 seconds
        for _ in range(60):  # Max 30 minutes
            if self._stop_event.is_set():
                return
            time.sleep(30)
            if self.data_engine.is_market_open():
                self.logger.info("🔔 Market Open!")
                return
        
    def _print_cycle_summary(self, cycle: int, result: dict):
        """Print Cycle Summary"""
        portfolio = self.risk_manager.get_portfolio_status()
        pnl_emoji = "💚" if portfolio["total_pnl"] >= 0 else "🔴"
        
        self.logger.info(
            f"📊 Cycle #{cycle} | "
            f"⏱️ {result['cycle_time_ms']}ms | "
            f"{pnl_emoji} PnL: ${portfolio['total_pnl']:+,.2f} | "
            f"📈 Positions: {portfolio['open_positions']} | "
            f"🎯 Win Rate: {portfolio['win_rate']:.0f}%"
        )

    def _signal_handler(self, signum, frame):
        """Handle Stop Signal"""
        self.logger.info("\n⏹️ Stop signal received...")
        self.running = False
        self._stop_event.set()

    def _shutdown(self):
        """Safe Shutdown"""
        self.logger.info("🔄 Shutting down...")
        
        # Print Final Status
        self.risk_manager.print_status()
        self.guardian.print_guardian_status()
        
        # Stop Streaming
        self.data_engine.stop_streaming()
        
        self.logger.info("👋 Bot stopped safely")

    # ══════════════════════════════════════════════════════
    # Interactive Commands
    # ══════════════════════════════════════════════════════

    def interactive_mode(self):
        """Interactive Mode for Quick Commands"""
        print("""
╔══════════════════════════════════════════════════════════════╗
║                🤖 Interactive Command Mode                   ║
╠══════════════════════════════════════════════════════════════╣
║  Available Commands:                                         ║
║                                                              ║
║  start          - Start Auto Trading                         ║
║  stop           - Stop Trading                               ║
║  status         - Portfolio Status                           ║
║  scan           - Scan Watchlist                             ║
║  analyze SYMBOL - Analyze Symbol                             ║
║  buy SYMBOL     - Quick Buy                                  ║
║  sell SYMBOL    - Sell/Close                                 ║
║  positions      - Open Positions                             ║
║  orders         - Pending Orders                             ║
║  guardian       - Guardian Status                            ║
║  emergency      - Emergency Exit (Close All)                 ║
║  config         - Current Config                             ║
║  quit           - Exit                                       ║
╚══════════════════════════════════════════════════════════════╝
""")
        
        while True:
            try:
                cmd = input("\n🤖 > ").strip().lower()
                
                if not cmd:
                    continue
                
                parts = cmd.split()
                command = parts[0]
                args = parts[1:] if len(parts) > 1 else []

                if command == "start":
                    threading.Thread(target=self.start, daemon=True).start()
                    print("🚀 Auto Trading Started in Background")

                elif command == "stop":
                    self.running = False
                    self._stop_event.set()
                    print("⏹️ Trading Stopped")

                elif command == "status":
                    self.risk_manager.print_status()
                    account = self.data_engine.get_account()
                    if account:
                        print(f"  💵 Buying Power: ${account.get('buying_power', 0):,.2f}")
                        print(f"  📊 Day Trades: {account.get('day_trade_count', 0)}")

                elif command == "scan":
                    print("🔍 Scanning...")
                    signals = self.trading_engine.scan_watchlist()
                    if signals:
                        print(f"\n📊 Found {len(signals)} signals:\n")
                        for s in signals:
                            emoji = "🟢" if s.direction == "buy" else "🔴"
                            print(f"  {emoji} {s.symbol:<6} | {s.direction:>4} | "
                                  f"Strength: {s.strength:.0%} | "
                                  f"Confidence: {s.confidence:.0%} | "
                                  f"Entry: ${s.entry_price:.2f} | "
                                  f"SL: ${s.stop_loss:.2f} | TP: ${s.take_profit:.2f}")
                            print(f"         Reason: {s.reason}")
                    else:
                        print("⚪ No signals found")

                elif command == "analyze" and args:
                    symbol = args[0].upper()
                    print(f"🔍 Analyzing {symbol}...")
                    signal = self.trading_engine.analyze_symbol(symbol)
                    if signal:
                        emoji = {"buy": "🟢", "sell": "🔴", "hold": "⚪"}[signal.direction]
                        print(f"\n  {emoji} Direction: {signal.direction.upper()}")
                        print(f"  💪 Strength: {signal.strength:.0%}")
                        print(f"  🎯 Confidence: {signal.confidence:.0%}")
                        print(f"  💲 Entry: ${signal.entry_price:.2f}")
                        print(f"  🛑 Stop: ${signal.stop_loss:.2f}")
                        print(f"  🎯 Target: ${signal.take_profit:.2f}")
                        print(f"  📝 Reason: {signal.reason}")
                        print(f"\n  Indicators:")
                        for k, v in signal.indicators.items():
                            print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")
                    else:
                        print(f"⚠️ Not enough data for {symbol}")

                elif command == "buy" and args:
                    symbol = args[0].upper()
                    qty = int(args[1]) if len(args) > 1 else None
                    print(f"🛒 Buying {symbol}...")
                    result = self.trading_engine.quick_buy(symbol, qty)
                    if "error" in result:
                        print(f"  ❌ {result['error']}")
                    else:
                        print(f"  ✅ Bought: {result.get('qty', 0)}x {symbol}")
                        print(f"  💲 Price: ${result.get('price', 0):.2f}")
                        levels = result.get("levels", {})
                        print(f"  🛑 Stop: ${levels.get('stop_loss', 0):.2f}")
                        print(f"  🎯 Target: ${levels.get('take_profit', 0):.2f}")

                elif command == "sell" and args:
                    symbol = args[0].upper()
                    print(f"📤 Selling {symbol}...")
                    result = self.trading_engine.quick_sell(symbol)
                    print(f"  {'✅' if 'error' not in result else '❌'} {result}")

                elif command == "positions":
                    positions = self.data_engine.get_positions()
                    if positions:
                        print(f"\n📊 {len(positions)} Open Positions:\n")
                        for p in positions:
                            pnl = p.get("unrealized_pl", 0)
                            emoji = "💚" if pnl >= 0 else "🔴"
                            print(f"  {emoji} {p['symbol']:<6} | "
                                  f"{p['quantity']:>4} Shares | "
                                  f"Entry: ${p['avg_entry_price']:.2f} | "
                                  f"Current: ${p['current_price']:.2f} | "
                                  f"PnL: ${pnl:+,.2f}")
                    else:
                        print("📭 No open positions")

                elif command == "orders":
                    orders = self.data_engine.get_open_orders()
                    if orders:
                        print(f"\n📋 {len(orders)} Pending Orders:\n")
                        for o in orders:
                            print(f"  📝 {o['symbol']:<6} | {o['side']:>4} | "
                                  f"{o['qty']} Sh | {o['type']} | {o['status']}")
                    else:
                        print("📭 No pending orders")

                elif command == "guardian":
                    self.guardian.print_guardian_status()

                elif command == "emergency":
                    confirm = input("  🆘 Are you sure? (yes/no): ")
                    if confirm.lower() in ("yes", "y"):
                        result = self.trading_engine.emergency_exit()
                        print(f"  🆘 {result['message']}")
                    else:
                        print("  ↩️ Cancelled")

                elif command == "config":
                    print_config()

                elif command in ("quit", "exit", "q"):
                    self.running = False
                    self._stop_event.set()
                    self._shutdown()
                    print("👋 Goodbye!")
                    break

                elif command == "help":
                    self.interactive_mode()
                    break

                elif command == "price" and args:
                    symbol = args[0].upper()
                    quote = self.data_engine.get_latest_quote(symbol)
                    print(f"  💲 {symbol}: Bid ${quote.get('bid', 0):.2f} | "
                          f"Ask ${quote.get('ask', 0):.2f} | "
                          f"Mid ${quote.get('mid', 0):.2f} | "
                          f"Spread {quote.get('spread_pct', 0):.3f}%")

                elif command == "market":
                    clock = self.data_engine.get_market_clock()
                    status = "🟢 Open" if clock.get("is_open") else "🔴 Closed"
                    print(f"  Market: {status}")
                    print(f"  Next Close: {clock.get('next_close', '-')}")
                    print(f"  Next Open: {clock.get('next_open', '-')}")

                else:
                    print(f"  ❓ Unknown command: {command}")
                    print("  💡 Type 'help' for available commands")

            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                self._shutdown()
                break
            except Exception as e:
                print(f"  ❌ Error: {e}")


# ══════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════

def main():
    setup_logging()
    
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║            🤖 Smart Scalper Bot - Alpaca API Trading         ║
║                                                              ║
║         ⚡ Fastest Response |  📊 Accurate Data |  🛡️ Zero Loss  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    mode = "paper" if PAPER_TRADING else "LIVE"
    print(f"  📌 Mode: {'📝 Paper Trading' if PAPER_TRADING else '💰 Live Trading ⚠️'}")
    print()
    
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "auto":
            bot = SmartScalperBot()
            bot.start()
        elif arg == "interactive":
            bot = SmartScalperBot()
            bot.interactive_mode()
        else:
            print(f"  ❓ Unknown mode: {arg}")
            print("  Usage: python bot.py [auto|interactive]")
    else:
        # Default: Interactive

        bot = SmartScalperBot()
        bot.interactive_mode()


if __name__ == "__main__":
    main()

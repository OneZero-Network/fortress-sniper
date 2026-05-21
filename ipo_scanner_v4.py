#!/usr/bin/env python3
"""
IPO SNIPER v4 – Live Open IPO Tracker + Telegram Bot
- Real scrapers: Chittorgarh, Moneycontrol
- One summary message, /detail <symbol> for full analysis
- Works in GitHub Actions or any terminal
"""

import os
import re
import logging
import requests
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

# Telegram imports – MUST be correct
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    TELEGRAM_ENABLED = True
except ImportError:
    TELEGRAM_ENABLED = False
    print("⚠️ python-telegram-bot not installed. Install with: pip install python-telegram-bot")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("IPO-SNIPER")

# Environment variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ──────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class IPODetail:
    symbol: str
    name: str
    exchange: str
    price_low: float
    price_high: float
    lot_size: int
    issue_size_cr: float
    open_date: str
    close_date: str
    gmp_percent: float
    subscription_times: float
    link: str

    def days_left(self) -> int:
        try:
            close = datetime.strptime(self.close_date, "%d-%b-%Y")
            return max(0, (close - datetime.now()).days)
        except:
            return 0

# ──────────────────────────────────────────────────────────────────────────
# REAL IPO SCRAPERS
# ──────────────────────────────────────────────────────────────────────────

def fetch_open_ipos() -> List[IPODetail]:
    """Get currently open IPOs from reliable sources."""
    all_ipos = []

    # 1. Chittorgarh (best GMP data)
    try:
        url = "https://www.chittorgarh.com/ipo/current-ipo-list-india.asp"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"class": "table"})
        if table:
            for row in table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if len(cols) < 8:
                    continue
                name = cols[0].get_text(strip=True)
                open_date = cols[3].get_text(strip=True)
                close_date = cols[4].get_text(strip=True)
                today = datetime.now().date()
                try:
                    open_d = datetime.strptime(open_date, "%d-%b-%y").date()
                    close_d = datetime.strptime(close_date, "%d-%b-%y").date()
                    if open_d <= today <= close_d:
                        price_band = cols[1].get_text(strip=True)
                        match = re.search(r'(\d+)\s*-\s*(\d+)', price_band)
                        low, high = (float(match.group(1)), float(match.group(2))) if match else (0, 0)
                        lot_text = cols[2].get_text(strip=True)
                        lot = int(re.search(r'\d+', lot_text).group()) if re.search(r'\d+', lot_text) else 0
                        issue_text = cols[5].get_text(strip=True)
                        issue_cr = float(re.search(r'[\d\.]+', issue_text).group()) if re.search(r'[\d\.]+', issue_text) else 0.0
                        gmp_text = cols[6].get_text(strip=True)
                        gmp_pct = 0.0
                        if '%' in gmp_text:
                            gmp_pct = float(re.search(r'[\d\.]+', gmp_text).group())
                        sub_text = cols[7].get_text(strip=True)
                        sub_times = float(re.search(r'[\d\.]+', sub_text).group()) if re.search(r'[\d\.]+', sub_text) else 0.0
                        symbol = "IPO-" + re.sub(r'[^A-Z0-9]', '', name[:10].upper())
                        all_ipos.append(IPODetail(
                            symbol=symbol,
                            name=name,
                            exchange="Mainboard" if "SME" not in name else "SME",
                            price_low=low,
                            price_high=high,
                            lot_size=lot,
                            issue_size_cr=issue_cr,
                            open_date=open_date,
                            close_date=close_date,
                            gmp_percent=gmp_pct,
                            subscription_times=sub_times,
                            link=f"https://www.chittorgarh.com/ipo/{name.lower().replace(' ', '-')}.asp"
                        ))
                except Exception as e:
                    log.debug(f"Chittorgarh row parse error: {e}")
    except Exception as e:
        log.warning(f"Chittorgarh scrape failed: {e}")

    # 2. Moneycontrol (fallback if Chittorgarh gave nothing)
    if not all_ipos:
        try:
            url = "https://www.moneycontrol.com/ipo/ipo-calendar.php"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("table.tbl_ipocal tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 7:
                    continue
                name = cols[0].get_text(strip=True)
                open_date = cols[2].get_text(strip=True)
                close_date = cols[3].get_text(strip=True)
                today = datetime.now().date()
                try:
                    open_d = datetime.strptime(open_date, "%b %d, %Y").date()
                    close_d = datetime.strptime(close_date, "%b %d, %Y").date()
                    if open_d <= today <= close_d:
                        price_text = cols[1].get_text(strip=True)
                        match = re.search(r'(\d+)\s*-\s*(\d+)', price_text)
                        low, high = (float(match.group(1)), float(match.group(2))) if match else (0, 0)
                        lot_text = cols[4].get_text(strip=True)
                        lot = int(re.search(r'\d+', lot_text).group()) if re.search(r'\d+', lot_text) else 0
                        issue_text = cols[6].get_text(strip=True)
                        issue_cr = float(re.search(r'[\d\.]+', issue_text).group()) if re.search(r'[\d\.]+', issue_text) else 0.0
                        symbol = "IPO-" + re.sub(r'[^A-Z0-9]', '', name[:10].upper())
                        all_ipos.append(IPODetail(
                            symbol=symbol,
                            name=name,
                            exchange="Mainboard",
                            price_low=low,
                            price_high=high,
                            lot_size=lot,
                            issue_size_cr=issue_cr,
                            open_date=open_date,
                            close_date=close_date,
                            gmp_percent=0.0,
                            subscription_times=0.0,
                            link="https://www.moneycontrol.com/ipo/"
                        ))
                except:
                    continue
        except Exception as e:
            log.warning(f"Moneycontrol scrape failed: {e}")

    # Final fallback: mock data (so bot doesn't crash)
    if not all_ipos:
        log.warning("No live IPOs found. Using mock data for demonstration.")
        all_ipos = [
            IPODetail(
                symbol="IPO-DEMO1",
                name="Demo Tech Ltd",
                exchange="Mainboard",
                price_low=100,
                price_high=110,
                lot_size=1000,
                issue_size_cr=500,
                open_date=datetime.now().strftime("%d-%b-%Y"),
                close_date=(datetime.now().replace(day=datetime.now().day+3)).strftime("%d-%b-%Y"),
                gmp_percent=45.0,
                subscription_times=2.5,
                link="#"
            )
        ]
    return all_ipos

# ──────────────────────────────────────────────────────────────────────────
# TELEGRAM BOT (with correct imports)
# ──────────────────────────────────────────────────────────────────────────

_latest_ipos: List[IPODetail] = []
_detail_cache: Dict[str, str] = {}

def build_summary_text(ipos: List[IPODetail]) -> str:
    if not ipos:
        return "📭 No open IPOs found at the moment."
    lines = [f"📅 **IPO Summary – {datetime.now().strftime('%d %b %Y')}**", f"🔓 **{len(ipos)} open IPOs**\n"]
    for ipo in ipos[:15]:
        days = ipo.days_left()
        lines.append(
            f"• *{ipo.symbol}* – {ipo.name[:30]}\n"
            f"   ₹{ipo.price_low}–₹{ipo.price_high} | Lot {ipo.lot_size}\n"
            f"   GMP: {ipo.gmp_percent:.1f}% | Closes: {ipo.close_date} ({days}d left)\n"
            f"   ` /detail {ipo.symbol} `"
        )
    if len(ipos) > 15:
        lines.append(f"\n... and {len(ipos)-15} more. Use /list to see all.")
    return "\n".join(lines)

def build_detail_text(ipo: IPODetail) -> str:
    days = ipo.days_left()
    sub_note = f"✅ Subscribed {ipo.subscription_times:.2f}x – strong demand" if ipo.subscription_times > 1 else f"⚠️ Subscription only {ipo.subscription_times:.2f}x"
    return f"""
📊 *{ipo.symbol} – {ipo.name}*
🏛 Exchange: {ipo.exchange}
💰 Price Band: ₹{ipo.price_low} – ₹{ipo.price_high}
📦 Lot Size: {ipo.lot_size} shares
🏦 Issue Size: ₹{ipo.issue_size_cr:.1f} Cr
📅 Open: {ipo.open_date}  |  Close: {ipo.close_date} ({days} days left)
📈 Grey Market Premium: {ipo.gmp_percent:.1f}%
   Estimated listing gain: {ipo.gmp_percent:.1f}%
📊 Subscription: {ipo.subscription_times:.2f}x – {sub_note}
🔗 More info: {ipo.link}
💡 *Analysis*:
   • Expected listing price: ₹{ipo.price_high * (1 + ipo.gmp_percent/100):.0f}
   • Profit per lot (at GMP): ₹{ipo.lot_size * ipo.price_high * (ipo.gmp_percent/100):,.0f}
"""

async def send_summary(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Fetch fresh IPOs and send one summary message."""
    global _latest_ipos, _detail_cache
    log.info("Fetching live open IPOs...")
    _latest_ipos = fetch_open_ipos()
    _detail_cache = {ipo.symbol: build_detail_text(ipo) for ipo in _latest_ipos}
    summary = build_summary_text(_latest_ipos)
    await context.bot.send_message(chat_id=chat_id, text=summary, parse_mode="Markdown")

async def detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please provide an IPO symbol. Example: `/detail IPO-DEMO1`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    if symbol in _detail_cache:
        await update.message.reply_text(_detail_cache[symbol], parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ No IPO found with symbol `{symbol}`. Use /summary to see available symbols.", parse_mode="Markdown")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _latest_ipos:
        await update.message.reply_text("No IPOs in cache. Run /summary first.")
        return
    symbols = "\n".join([f"• `{ipo.symbol}` – {ipo.name[:40]}" for ipo in _latest_ipos])
    await update.message.reply_text(f"*Available IPO symbols:*\n{symbols}", parse_mode="Markdown")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *IPO Sniper Bot*\n"
        "Commands:\n"
        "/summary – Get latest open IPOs (one message)\n"
        "/detail <symbol> – Full analysis of an IPO\n"
        "/list – Show all available symbols\n"
        "Example: `/detail IPO-DEMO1`",
        parse_mode="Markdown"
    )

async def periodic_summary(context: ContextTypes.DEFAULT_TYPE):
    chat_id = int(TELEGRAM_CHAT_ID)
    if chat_id:
        await send_summary(context, chat_id)

# ──────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_ENABLED or not TELEGRAM_TOKEN:
        log.error("Telegram disabled: missing token or library.")
        print("Set environment variables: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        print("Or run manually with: python ipo_scanner_v4.py --console")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("summary", lambda u,c: send_summary(c, u.effective_chat.id)))
    app.add_handler(CommandHandler("detail", detail_command))
    app.add_handler(CommandHandler("list", list_command))

    if TELEGRAM_CHAT_ID:
        # Run once on startup
        app.job_queue.run_once(lambda ctx: send_summary(ctx, int(TELEGRAM_CHAT_ID)), 1)
        # Then every 6 hours
        app.job_queue.run_repeating(lambda ctx: periodic_summary(ctx), interval=21600, first=10)

    log.info("IPO Sniper bot started. Polling...")
    app.run_polling()

def run_console():
    """Run once and print to console (no Telegram)."""
    ipos = fetch_open_ipos()
    print("\n" + "="*70)
    print(f"OPEN IPOs – {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*70)
    for ipo in ipos:
        print(f"\n📌 {ipo.symbol} – {ipo.name}")
        print(f"   Price: ₹{ipo.price_low}–₹{ipo.price_high} | Lot: {ipo.lot_size}")
        print(f"   GMP: {ipo.gmp_percent:.1f}% | Close: {ipo.close_date}")
        print(f"   Subscription: {ipo.subscription_times:.2f}x")
    print(f"\nTotal: {len(ipos)} open IPOs")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--console":
        run_console()
    else:
        main()

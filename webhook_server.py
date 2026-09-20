import os
import time
import logging
from flask import Flask, request, jsonify
import requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook")

app = Flask(__name__)

# ===== CONFIG (from environment variables - never hard-code secrets) =====
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@Azhar5mSignal")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")  # optional shared-secret check

VALID_PAIRS = {
    "AUD/NZD", "NZD/CHF", "NZD/JPY", "EUR/JPY",
    "EUR/NZD", "GBP/AUD", "CAD/JPY",
}
VALID_DIRECTIONS = {"BUY", "SELL"}

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# ===== DUPLICATE PROTECTION =====
# Keeps the last signal key + timestamp seen. Same pair+direction within
# DEDUP_WINDOW_SECONDS is treated as a duplicate and skipped.
DEDUP_WINDOW_SECONDS = 240  # slightly under one 5-min candle
_last_signals = {}  # key: "pair|direction" -> last-sent unix timestamp


def is_duplicate(pair, direction):
    key = f"{pair}|{direction}"
    now = time.time()
    last_time = _last_signals.get(key)
    if last_time is not None and (now - last_time) < DEDUP_WINDOW_SECONDS:
        return True
    _last_signals[key] = now
    return False


def send_telegram_message(text):
    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set")
        return False, "Server misconfigured: missing bot token"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(TELEGRAM_API_URL, json=payload, timeout=10)
        data = resp.json()
        if not data.get("ok"):
            log.error(f"Telegram API error: {data}")
            return False, str(data)
        return True, None
    except Exception as e:
        log.exception("Failed to reach Telegram API")
        return False, str(e)


def format_signal_message(pair, direction, timeframe, expiry):
    emoji = "\U0001F4C8" if direction == "BUY" else "\U0001F4C9"
    return (
        "\U0001F525 <b>AZHAR 5M SIGNAL</b> \U0001F525\n\n"
        f"\U0001F4B1 Pair: <b>{pair}</b>\n"
        f"\u23F1 Timeframe: {timeframe}M\n"
        f"{emoji} Direction: <b>{direction}</b>\n"
        f"\u231B Expiry: {expiry} MIN\n\n"
        "Signal candle close hone ke baad next candle entry honi hai."
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    # Optional shared-secret check (recommended): TradingView can't send custom
    # headers, so if you set WEBHOOK_SECRET, put it INSIDE the alert JSON as a
    # field (e.g. "secret":"xxxx") and check it here instead. Left as a no-op
    # unless you wire it up.
    raw = request.get_data(as_text=True)
    log.info(f"Raw payload received: {raw}")

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"ok": False, "error": "Invalid or missing JSON body"}), 400

    pair = str(data.get("pair", "")).strip()
    direction = str(data.get("direction", "")).strip().upper()
    timeframe = str(data.get("timeframe", "5")).strip()
    expiry = str(data.get("expiry", "5")).strip()

    if pair not in VALID_PAIRS:
        return jsonify({"ok": False, "error": f"Unknown/unsupported pair: {pair}"}), 400
    if direction not in VALID_DIRECTIONS:
        return jsonify({"ok": False, "error": f"Invalid direction: {direction}"}), 400

    if is_duplicate(pair, direction):
        log.info(f"Duplicate signal skipped: {pair} {direction}")
        return jsonify({"ok": True, "skipped": "duplicate"}), 200

    message = format_signal_message(pair, direction, timeframe, expiry)
    sent_ok, err = send_telegram_message(message)
    if not sent_ok:
        return jsonify({"ok": False, "error": f"Telegram send failed: {err}"}), 502

    return jsonify({"ok": True, "sent": True, "pair": pair, "direction": direction}), 200


@app.route("/test", methods=["GET"])
def test():
    """Manually hit this endpoint (in a browser or curl) to verify the
    server -> Telegram path works, without needing TradingView at all."""
    message = format_signal_message("EUR/JPY", "BUY", "5", "5")
    sent_ok, err = send_telegram_message("\u2705 TEST SIGNAL \u2705\n\n" + message)
    if not sent_ok:
        return jsonify({"ok": False, "error": err}), 502
    return jsonify({"ok": True, "message": "Test signal sent to Telegram"}), 200


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "running"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

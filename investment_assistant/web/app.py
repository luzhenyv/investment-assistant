"""
Web interface — zone management + watchlist overview.
Minimal Flask app. No auth (personal tool on local network).

Run:  python web/app.py
      http://localhost:5000
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, request, redirect, url_for, jsonify
from core.database import init_db
from core.zone_store import (
    add_zone, update_zone, deactivate_zone, flip_zone,
    get_zones, get_zone_by_id, get_all_active_zones,
)
from core.price_feed import get_latest_close
from config import WATCHLIST, MACRO_SYMBOLS

app = Flask(__name__, template_folder="templates")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Watchlist overview: each stock + its current price + zone count."""
    all_zones = get_all_active_zones()
    watchlist_data = []
    for symbol in WATCHLIST:
        zones = all_zones.get(symbol, [])
        price = get_latest_close(symbol)
        watchlist_data.append({
            "symbol": symbol,
            "price":  price,
            "zones":  zones,
            "zone_count": len(zones),
        })
    return render_template("index.html", watchlist=watchlist_data)


@app.route("/stock/<symbol>")
def stock_detail(symbol: str):
    symbol = symbol.upper()
    zones  = get_zones(symbol)
    price  = get_latest_close(symbol)
    return render_template("stock.html", symbol=symbol, zones=zones, price=price)


@app.route("/stock/<symbol>/zone/add", methods=["POST"])
def zone_add(symbol: str):
    symbol = symbol.upper()
    add_zone(
        symbol   = symbol,
        low      = float(request.form["low"]),
        high     = float(request.form["high"]),
        strength = request.form["strength"],
        note     = request.form.get("note", ""),
    )
    return redirect(url_for("stock_detail", symbol=symbol))


@app.route("/zone/<int:zone_id>/edit", methods=["POST"])
def zone_edit(zone_id: int):
    zone = get_zone_by_id(zone_id)
    if not zone:
        return "Zone not found", 404
    update_zone(
        zone_id,
        low      = float(request.form["low"]),
        high     = float(request.form["high"]),
        strength = request.form["strength"],
        note     = request.form.get("note", ""),
    )
    return redirect(url_for("stock_detail", symbol=zone["symbol"]))


@app.route("/zone/<int:zone_id>/deactivate", methods=["POST"])
def zone_deactivate(zone_id: int):
    zone = get_zone_by_id(zone_id)
    symbol = zone["symbol"] if zone else "/"
    deactivate_zone(zone_id)
    return redirect(url_for("stock_detail", symbol=symbol))


@app.route("/zone/<int:zone_id>/flip", methods=["POST"])
def zone_flip(zone_id: int):
    zone = get_zone_by_id(zone_id)
    symbol = zone["symbol"] if zone else "/"
    flip_zone(zone_id)
    return redirect(url_for("stock_detail", symbol=symbol))


# ── JSON API (for future use / mobile) ────────────────────────────────────────

@app.route("/api/zones/<symbol>")
def api_zones(symbol: str):
    return jsonify(get_zones(symbol.upper()))


@app.route("/api/price/<symbol>")
def api_price(symbol: str):
    price = get_latest_close(symbol.upper())
    return jsonify({"symbol": symbol.upper(), "price": price})


# ── Boot ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)

"""
Web interface — zone management + watchlist overview.
Minimal FastAPI app. No auth (personal tool on local network).

Run:  uvicorn investment_assistant.web.app:app --reload
      http://localhost:8000
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from core.database import init_db
from core.zone_store import (
    add_zone, update_zone, deactivate_zone, flip_zone,
    get_zones, get_zone_by_id, get_all_active_zones,
)
from core.price_feed import get_latest_close
from config import WATCHLIST, MACRO_SYMBOLS

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app = FastAPI(title="Investment Assistant Web")


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def index(request: Request):
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
    return templates.TemplateResponse(
        request,
        "index.html",
        {"watchlist": watchlist_data},
    )


@app.get("/stock/{symbol}")
def stock_detail(request: Request, symbol: str):
    symbol = symbol.upper()
    zones  = get_zones(symbol)
    price  = get_latest_close(symbol)
    return templates.TemplateResponse(
        request,
        "stock.html",
        {"symbol": symbol, "zones": zones, "price": price},
    )


@app.post("/stock/{symbol}/zone/add")
def zone_add(
    symbol: str,
    low: float = Form(...),
    high: float = Form(...),
    strength: str = Form(...),
    note: str = Form(""),
):
    symbol = symbol.upper()
    add_zone(
        symbol   = symbol,
        low      = low,
        high     = high,
        strength = strength,
        note     = note,
    )
    return RedirectResponse(url=f"/stock/{symbol}", status_code=303)


@app.post("/zone/{zone_id}/edit")
def zone_edit(
    zone_id: int,
    low: float = Form(...),
    high: float = Form(...),
    strength: str = Form(...),
    note: str = Form(""),
):
    zone = get_zone_by_id(zone_id)
    if not zone:
        return JSONResponse({"error": "Zone not found"}, status_code=404)
    update_zone(
        zone_id,
        low      = low,
        high     = high,
        strength = strength,
        note     = note,
    )
    return RedirectResponse(url=f"/stock/{zone['symbol']}", status_code=303)


@app.post("/zone/{zone_id}/deactivate")
def zone_deactivate(zone_id: int):
    zone = get_zone_by_id(zone_id)
    symbol = zone["symbol"] if zone else "/"
    deactivate_zone(zone_id)
    if symbol == "/":
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url=f"/stock/{symbol}", status_code=303)


@app.post("/zone/{zone_id}/flip")
def zone_flip(zone_id: int):
    zone = get_zone_by_id(zone_id)
    symbol = zone["symbol"] if zone else "/"
    flip_zone(zone_id)
    if symbol == "/":
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url=f"/stock/{symbol}", status_code=303)


# ── JSON API (for future use / mobile) ────────────────────────────────────────

@app.get("/api/zones/{symbol}")
def api_zones(symbol: str):
    return get_zones(symbol.upper())


@app.get("/api/price/{symbol}")
def api_price(symbol: str):
    price = get_latest_close(symbol.upper())
    return {"symbol": symbol.upper(), "price": price}


# ── Boot ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("investment_assistant.web.app:app", host="0.0.0.0", port=8000, reload=True)

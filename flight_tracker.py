"""
Daily Flight Tracker: MSP → Tokyo (round trip, 2 pax)
Uses SerpAPI (Google Flights) and sends Pushover notifications.
Searches 3 date combos/day to stay under the 100/month free tier.

Requirements tracked: refundable, checked bag included, 2 passengers.
Note: Google Flights doesn't filter by refundable/checked bags directly,
so the script fetches all results and includes bag pricing info.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
from serpapi import GoogleSearch

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "flight_tracker.log"),
    ],
)
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
SERPAPI_KEY = os.environ["SERPAPI_KEY"]
PUSHOVER_USER = os.environ["PUSHOVER_USER_KEY"]
PUSHOVER_TOKEN = os.environ["PUSHOVER_APP_TOKEN"]

BASE_DEPART = datetime(2026, 3, 18)
BASE_RETURN = datetime(2026, 6, 3)
TRIP_LENGTH = (BASE_RETURN - BASE_DEPART).days  # 77 days
PAX = 2

HISTORY_FILE = Path(__file__).parent / "price_history.json"

# Rotate through date offset pairs daily to cover flexibility
# while using only 3 API calls/day (90/month < 100 free limit).
DATE_OFFSET_SCHEDULE = [
    [(-3, -3), (0, 0), (3, 3)],
    [(-2, -2), (1, 1), (-3, 0)],
    [(-1, -1), (2, 2), (0, 3)],
    [(-3, -1), (0, 2), (3, 0)],
    [(0, -3), (-2, 1), (1, -2)],
    [(-1, 2), (2, -1), (-3, 3)],
    [(3, -3), (-2, 0), (1, 3)],
]


def get_date_combos_for_today():
    """Pick 3 date offset pairs based on the day of year (rotates weekly)."""
    day_index = datetime.now().timetuple().tm_yday % len(DATE_OFFSET_SCHEDULE)
    offsets = DATE_OFFSET_SCHEDULE[day_index]
    combos = []
    for depart_off, return_off in offsets:
        dep = BASE_DEPART + timedelta(days=depart_off)
        ret = dep + timedelta(days=TRIP_LENGTH + return_off)
        combos.append((dep.strftime("%Y-%m-%d"), ret.strftime("%Y-%m-%d")))
    return combos


def search_flights(depart_date, return_date):
    """Search Google Flights via SerpAPI for MSP→Tokyo round trip."""
    params = {
        "engine": "google_flights",
        "departure_id": "MSP",
        "arrival_id": "NRT,HND",  # Tokyo Narita + Haneda explicitly
        "outbound_date": depart_date,
        "return_date": return_date,
        "adults": PAX,
        "currency": "USD",
        "hl": "en",
        "type": "1",  # round trip
        "sort_by": "2",  # sort by price
        "api_key": SERPAPI_KEY,
    }

    log.info("Searching MSP→Tokyo  %s to %s (%d pax)", depart_date, return_date, PAX)

    try:
        search = GoogleSearch(params)
        results = search.get_dict()
    except Exception as e:
        log.error("SerpAPI error: %s", e)
        return []

    if "error" in results:
        log.warning("SerpAPI returned error: %s", results["error"])
        return []

    flights = []

    for category in ["best_flights", "other_flights"]:
        for flight in results.get(category, []):
            parsed = parse_flight(flight, depart_date, return_date, category)
            if parsed:
                flights.append(parsed)

    log.info("  Found %d flights", len(flights))
    return flights


def parse_flight(flight, depart_date, return_date, category):
    """Parse a SerpAPI Google Flights result."""
    price = flight.get("price")
    if price is None:
        return None

    total_price = price  # Google Flights shows total for all passengers

    def summarize_legs(legs):
        if not legs:
            return {}
        first = legs[0]
        last = legs[-1]
        airlines = []
        for leg in legs:
            airline = leg.get("airline", "??")
            if airline not in airlines:
                airlines.append(airline)
        dep_airport = first.get("departure_airport", {})
        arr_airport = last.get("arrival_airport", {})
        return {
            "origin": dep_airport.get("id", "?"),
            "dest": arr_airport.get("id", "?"),
            "depart_time": dep_airport.get("time", ""),
            "arrive_time": arr_airport.get("time", ""),
            "airlines": ", ".join(airlines),
        }

    outbound_legs = flight.get("flights", [])
    extensions = flight.get("extensions", [])

    return {
        "price_total": total_price,
        "price_per_person": total_price / PAX,
        "outbound": summarize_legs(outbound_legs),
        "duration_min": flight.get("total_duration", 0),
        "stops": len(outbound_legs) - 1 if outbound_legs else 0,
        "airlines": ", ".join(
            dict.fromkeys(l.get("airline", "") for l in outbound_legs)
        ),
        "extensions": extensions,
        "category": category,
        "search_dates": {"depart": depart_date, "return": return_date},
        "carbon_emissions": flight.get("carbon_emissions", {}),
    }


def format_duration(minutes):
    if not minutes:
        return "?"
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m}m"


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {"lowest_ever": None, "runs": []}


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def send_pushover(title, message, priority=0, url=None):
    data = {
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "title": title,
        "message": message,
        "priority": priority,
        "sound": "cashregister",
    }
    if url:
        data["url"] = url
        data["url_title"] = "View on Google Flights"
    resp = requests.post(
        "https://api.pushover.net/1/messages.json", data=data, timeout=15
    )
    resp.raise_for_status()
    log.info("Pushover notification sent.")


def build_google_flights_url(depart, ret):
    return (
        f"https://www.google.com/travel/flights?q=Flights+from+MSP+to+Tokyo"
        f"+on+{depart}+return+{ret}+{PAX}+passengers"
    )


def main():
    log.info("=== Flight Tracker starting ===")

    date_combos = get_date_combos_for_today()
    all_results = []

    for depart_date, return_date in date_combos:
        flights = search_flights(depart_date, return_date)
        all_results.extend(flights)

    if not all_results:
        log.warning("No flights found.")
        send_pushover(
            "Flight Tracker - No Results",
            "No MSP to Tokyo flights found today. Will retry tomorrow.",
            priority=-1,
        )
        return

    # Sort by total price
    all_results.sort(key=lambda x: x["price_total"])

    top = all_results[:5]
    best = top[0]

    # Price history
    history = load_history()
    prev_lowest = history.get("lowest_ever")
    new_low = prev_lowest is None or best["price_total"] < prev_lowest

    history["runs"].append(
        {
            "date": datetime.now().isoformat(),
            "best_price": best["price_total"],
            "results_count": len(all_results),
        }
    )
    history["runs"] = history["runs"][-90:]
    if new_low:
        history["lowest_ever"] = best["price_total"]
    save_history(history)

    # Build notification
    lines = []
    if new_low and prev_lowest is not None:
        lines.append(f"*** NEW LOW! (was ${prev_lowest:,.0f}) ***\n")

    for i, f in enumerate(top, 1):
        ob = f["outbound"]
        dates = f["search_dates"]
        ext = f.get("extensions", [])
        ext_str = " | ".join(ext[:3]) if ext else ""

        lines.append(
            f"#{i}  ${f['price_total']:,.0f} total "
            f"(${f['price_per_person']:,.0f}/pp)\n"
            f"  {ob.get('origin', 'MSP')}->{ob.get('dest', 'TYO')}  "
            f"{format_duration(f['duration_min'])}  "
            f"{f['stops']} stop(s)  {f['airlines']}\n"
            f"  {dates['depart']} -> {dates['return']}"
        )
        if ext_str:
            lines.append(f"  {ext_str}")

    lines.append(
        f"\n{len(all_results)} flights scanned. "
        f"Prices are for {PAX} pax."
    )
    lines.append(
        "TIP: When booking, add checked bags + "
        "select refundable fare at checkout."
    )

    message = "\n".join(lines)

    gf_url = build_google_flights_url(
        best["search_dates"]["depart"],
        best["search_dates"]["return"],
    )

    priority = 1 if new_low and prev_lowest else 0
    send_pushover(
        f"Flights: ${best['price_total']:,.0f} MSP<->Tokyo ({PAX}pax)",
        message,
        priority=priority,
        url=gf_url,
    )

    log.info("Best: $%s total. Done.", best["price_total"])


if __name__ == "__main__":
    main()

import os
import yaml
import requests
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

from db import init_db, insert_price_snapshot, get_previous_price, was_recently_notified, insert_notification
from flights_client import search_best_in_range, QuotaExceededError, InvalidApiKeyError

load_dotenv()

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }, timeout=15).raise_for_status()


def price_change_label(current, previous, currency):
    if previous is None:
        return "🆕 First check"
    diff = current - previous["price"]
    if abs(diff) < 1:
        return "➡ No change"
    if diff < 0:
        return f"↓ {abs(diff):,.0f} {currency} cheaper than yesterday"
    return f"↑ {diff:,.0f} {currency} more than yesterday"


def build_daily_summary(results, today):
    lines = [f"🗓 Daily Flight Summary — {today.strftime('%d %b %Y')}\n"]
    for r in results:
        trip_type = "Round trip" if r["return_date"] else "One way"
        stops_label = "Direct" if r["stops"] == 0 else f"{r['stops']} stop{'s' if r['stops'] > 1 else ''}"

        lines.append(f"✈ {r['origin']} → {r['destination']}  ({trip_type})")

        if r["return_date"]:
            lines.append(f"   📅 Outbound: {r['outbound_date']} → Return: {r['return_date']}")
        else:
            lines.append(f"   📅 {r['outbound_date']}")

        lines.append(f"   💰 {r['price']:,.0f} {r['currency']}  ({r['change_label']})")
        lines.append(f"   ✈ {r['airline']}  |  {stops_label}")

        if r["deep_link"]:
            lines.append(f"   🔗 {r['deep_link']}")

        lines.append("")

    return "\n".join(lines).strip()


def build_drop_alert(r):
    stops_label = "Direct" if r["stops"] == 0 else f"{r['stops']} stop{'s' if r['stops'] > 1 else ''}"
    date_line = r["outbound_date"]
    if r["return_date"]:
        date_line += f" → {r['return_date']}"
    lines = [
        "🚨 Price Drop Alert!\n",
        f"✈ {r['origin']} → {r['destination']}",
        f"   📅 {date_line}",
        f"   💰 {r['price']:,.0f} {r['currency']}  ({r['change_label']})",
        f"   ✈ {r['airline']}  |  {stops_label}",
    ]
    if r["deep_link"]:
        lines.append(f"   🔗 {r['deep_link']}")
    return "\n".join(lines)


def run():
    config = load_config()
    settings = config.get("settings", {})
    alert_mode = settings.get("alert_mode", "daily")
    drop_threshold_pct = settings.get("price_drop_threshold_pct", 10)
    max_samples = settings.get("max_samples_per_route", 3)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    init_db()
    today = date.today()
    results = []

    for route in config.get("routes", []):
        if not route.get("active", True):
            continue

        origin = route["origin"]
        destination = route["destination"]
        currency = route.get("currency", "EUR")
        outbound = route["outbound_date_range"]
        ret = route.get("return_date_range")

        try:
            flight = search_best_in_range(
                origin=origin,
                destination=destination,
                outbound_from=outbound["from"],
                outbound_to=outbound["to"],
                return_from=ret["from"] if ret else None,
                return_to=ret["to"] if ret else None,
                max_price=route.get("max_price"),
                max_stops=route.get("max_stops"),
                currency=currency,
                max_samples=max_samples,
            )
        except QuotaExceededError:
            send_telegram(token, chat_id,
                "⚠️ Flight search stopped — SerpAPI free tier monthly quota is exhausted.\n\n"
                "No more searches can run until the quota resets on the 1st of next month.\n"
                "To continue sooner, upgrade your SerpAPI plan at serpapi.com.")
            return
        except InvalidApiKeyError:
            send_telegram(token, chat_id,
                "❌ Flight search failed — the SerpAPI key in .env is missing or invalid.\n\n"
                "Check SERPAPI_KEY in /home/danielspi-server/open-claw/.env and restart.")
            return

        if not flight:
            continue

        previous = get_previous_price(
            origin=origin,
            destination=destination,
            departure_date=flight["outbound_date"],
            return_date=flight.get("return_date"),
        )

        insert_price_snapshot(
            origin=origin,
            destination=destination,
            departure_date=flight["outbound_date"],
            return_date=flight.get("return_date"),
            price=flight["price"],
            currency=currency,
            airline=flight["airline"],
            stops=flight["stops"],
            deep_link=flight["deep_link"],
        )

        change_label = price_change_label(flight["price"], previous, currency)

        result = {
            "origin": origin,
            "destination": destination,
            "outbound_date": flight["outbound_date"],
            "return_date": flight.get("return_date"),
            "price": flight["price"],
            "currency": currency,
            "airline": flight["airline"],
            "stops": flight["stops"],
            "deep_link": flight["deep_link"],
            "change_label": change_label,
            "previous": previous,
        }
        results.append(result)

        # Immediate alert if price dropped past threshold
        if alert_mode in ("immediate", "both") and previous:
            prev_price = previous["price"]
            drop_pct = ((prev_price - flight["price"]) / prev_price) * 100
            if drop_pct >= drop_threshold_pct:
                if not was_recently_notified(origin, destination, flight["outbound_date"], flight.get("return_date")):
                    send_telegram(token, chat_id, build_drop_alert(result))
                    insert_notification(origin, destination, flight["outbound_date"],
                                        flight["price"], currency, flight.get("return_date"),
                                        triggered_by="immediate_alert")

    # Daily summary — always sends if alert_mode includes daily
    if results and alert_mode in ("daily", "both"):
        send_telegram(token, chat_id, build_daily_summary(results, today))
        for r in results:
            if not was_recently_notified(r["origin"], r["destination"], r["outbound_date"], r.get("return_date")):
                insert_notification(r["origin"], r["destination"], r["outbound_date"],
                                    r["price"], r["currency"], r.get("return_date"),
                                    triggered_by="cron")


if __name__ == "__main__":
    run()

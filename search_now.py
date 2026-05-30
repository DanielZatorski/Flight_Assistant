import argparse
import os
import sys
from dotenv import load_dotenv
from flights_client import search_flights, search_best_in_range, extract_cheapest, QuotaExceededError, InvalidApiKeyError

load_dotenv()


def format_result(flight, origin, destination, currency):
    if not flight:
        return f"No flights found for {origin} → {destination} with the given criteria."

    stops_label = "Direct" if flight["stops"] == 0 else f"{flight['stops']} stop{'s' if flight['stops'] > 1 else ''}"
    trip_label = f"{flight['outbound_date']}"
    if flight.get("return_date"):
        trip_label += f" → Return: {flight['return_date']}"

    lines = [
        f"✈ {origin} → {destination}",
        f"   📅 {trip_label}",
        f"   💰 {flight['price']:,.0f} {currency}",
        f"   ✈ {flight['airline']}  |  {stops_label}",
    ]
    if flight.get("total_duration_min"):
        hours, mins = divmod(flight["total_duration_min"], 60)
        lines.append(f"   ⏱ {hours}h {mins}m total")
    if flight.get("deep_link"):
        lines.append(f"   🔗 {flight['deep_link']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Ad-hoc flight search via SerpAPI")
    parser.add_argument("--origin",       required=True,  help="Departure IATA code e.g. CPH")
    parser.add_argument("--destination",  required=True,  help="Arrival IATA code e.g. GIG")
    parser.add_argument("--outbound",     help="Specific outbound date YYYY-MM-DD")
    parser.add_argument("--return-date",  dest="return_date", help="Specific return date YYYY-MM-DD")
    parser.add_argument("--outbound-from",dest="outbound_from", help="Outbound date range start YYYY-MM-DD")
    parser.add_argument("--outbound-to",  dest="outbound_to",   help="Outbound date range end YYYY-MM-DD")
    parser.add_argument("--return-from",  dest="return_from",   help="Return date range start YYYY-MM-DD")
    parser.add_argument("--return-to",    dest="return_to",     help="Return date range end YYYY-MM-DD")
    parser.add_argument("--max-stops",    dest="max_stops", type=int, default=None)
    parser.add_argument("--currency",     default="EUR")
    parser.add_argument("--max-price",    dest="max_price", type=int, default=None)
    parser.add_argument("--samples",      type=int, default=3, help="Date samples for range search")
    args = parser.parse_args()

    origin      = args.origin.upper()
    destination = args.destination.upper()

    try:
        # Specific date search
        if args.outbound:
            data = search_flights(
                origin=origin,
                destination=destination,
                outbound_date=args.outbound,
                return_date=args.return_date,
                max_stops=args.max_stops,
                currency=args.currency,
                max_price=args.max_price,
            )
            flight = extract_cheapest(data)
            if flight:
                flight["outbound_date"] = args.outbound
                flight["return_date"]   = args.return_date

        # Date range search
        elif args.outbound_from and args.outbound_to:
            flight = search_best_in_range(
                origin=origin,
                destination=destination,
                outbound_from=args.outbound_from,
                outbound_to=args.outbound_to,
                return_from=args.return_from,
                return_to=args.return_to,
                max_stops=args.max_stops,
                currency=args.currency,
                max_price=args.max_price,
                max_samples=args.samples,
            )
        else:
            print("Error: provide --outbound or --outbound-from/--outbound-to")
            sys.exit(1)

    except QuotaExceededError:
        print(
            "⚠️ Sorry, the SerpAPI free tier monthly quota is exhausted — "
            "no more flight searches can run until it resets on the 1st of next month."
        )
        sys.exit(1)
    except InvalidApiKeyError:
        print(
            "❌ Flight search failed — the SerpAPI key is missing or invalid. "
            "Check SERPAPI_KEY in /home/danielspi-server/open-claw/.env."
        )
        sys.exit(1)

    print(format_result(flight, origin, destination, args.currency))


if __name__ == "__main__":
    main()

import os
import requests
from datetime import datetime, date, timedelta

SERPAPI_ENDPOINT = "https://serpapi.com/search"

QUOTA_KEYWORDS = ("run out", "exceeded", "monthly", "quota", "out of searches")
KEY_KEYWORDS   = ("invalid api key", "invalid key", "api_key")


class QuotaExceededError(Exception):
    """Raised when the SerpAPI free tier monthly limit is exhausted."""
    pass


class InvalidApiKeyError(Exception):
    """Raised when the SerpAPI key is missing or rejected."""
    pass


def _check_serpapi_error(data):
    """Raise a typed exception if SerpAPI returned an error payload."""
    error_msg = data.get("error", "")
    if not error_msg:
        return
    lower = error_msg.lower()
    if any(k in lower for k in QUOTA_KEYWORDS):
        raise QuotaExceededError(error_msg)
    if any(k in lower for k in KEY_KEYWORDS):
        raise InvalidApiKeyError(error_msg)
    raise requests.RequestException(f"SerpAPI error: {error_msg}")


def search_flights(origin, destination, outbound_date, return_date=None,
                   adults=1, max_price=None, max_stops=None, currency="EUR"):
    """Single SerpAPI Google Flights call for a specific date."""
    params = {
        "engine": "google_flights",
        "api_key": os.getenv("SERPAPI_KEY"),
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "adults": adults,
        "currency": currency,
        "type": 1 if return_date else 2,  # 1=round trip, 2=one way
    }
    if return_date:
        params["return_date"] = return_date
    if max_price is not None:
        params["max_price"] = max_price
    if max_stops is not None:
        params["stops"] = max_stops

    resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=30)

    # HTTP 429 means rate limit or quota hit at the network level
    if resp.status_code == 429:
        raise QuotaExceededError("SerpAPI monthly quota exhausted (HTTP 429)")

    resp.raise_for_status()
    data = resp.json()
    _check_serpapi_error(data)
    return data


def extract_cheapest(data):
    """Pull the cheapest flight out of a SerpAPI response."""
    all_flights = data.get("best_flights", []) + data.get("other_flights", [])
    if not all_flights:
        return None

    all_flights.sort(key=lambda x: x.get("price", float("inf")))
    cheapest = all_flights[0]

    legs = cheapest.get("flights", [])
    airline = legs[0].get("airline", "Unknown") if legs else "Unknown"
    stops = len(cheapest.get("layovers", []))
    deep_link = data.get("search_metadata", {}).get("google_flights_url", "")

    return {
        "price": cheapest.get("price"),
        "airline": airline,
        "stops": stops,
        "total_duration_min": cheapest.get("total_duration"),
        "deep_link": deep_link,
    }


def search_best_in_range(origin, destination, outbound_from, outbound_to,
                          return_from=None, return_to=None,
                          max_price=None, max_stops=None, currency="EUR",
                          max_samples=3):
    """
    Sample up to max_samples evenly spaced dates across the outbound range.
    Returns the cheapest result found. Designed to stay within SerpAPI's
    250 calls/month free tier - at max_samples=3 and 2 routes, daily cron
    uses ~180 calls/month.
    """
    start = datetime.strptime(outbound_from, "%Y-%m-%d").date()
    end = datetime.strptime(outbound_to, "%Y-%m-%d").date()
    total_days = (end - start).days
    today = date.today()

    if total_days <= 0:
        sample_dates = [start]
    elif total_days < max_samples:
        sample_dates = [start + timedelta(days=i) for i in range(total_days + 1)]
    else:
        step = total_days // (max_samples - 1)
        sample_dates = [start + timedelta(days=i * step) for i in range(max_samples)]

    sample_dates = [d for d in sample_dates if d > today]
    if not sample_dates:
        return None

    results = []
    for outbound_date in sample_dates:
        return_date = None
        if return_from:
            ret_start = datetime.strptime(return_from, "%Y-%m-%d").date()
            # Return date must be after outbound
            return_date = max(ret_start, outbound_date + timedelta(days=1))
            return_date = return_date.strftime("%Y-%m-%d")

        try:
            data = search_flights(
                origin=origin,
                destination=destination,
                outbound_date=outbound_date.strftime("%Y-%m-%d"),
                return_date=return_date,
                max_price=max_price,
                max_stops=max_stops,
                currency=currency,
            )
            flight = extract_cheapest(data)
            if flight and flight["price"] is not None:
                flight["outbound_date"] = outbound_date.strftime("%Y-%m-%d")
                flight["return_date"] = return_date
                results.append(flight)
        except requests.RequestException:
            continue

    if not results:
        return None

    return min(results, key=lambda x: x["price"])

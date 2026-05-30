import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "openclaw.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                origin        TEXT    NOT NULL,
                destination   TEXT    NOT NULL,
                departure_date TEXT   NOT NULL,
                return_date   TEXT,
                price         REAL    NOT NULL,
                currency      TEXT    NOT NULL,
                airline       TEXT,
                stops         INTEGER NOT NULL DEFAULT 0,
                deep_link     TEXT,
                fetched_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS notifications_sent (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                origin         TEXT    NOT NULL,
                destination    TEXT    NOT NULL,
                departure_date TEXT    NOT NULL,
                return_date    TEXT,
                price          REAL    NOT NULL,
                currency       TEXT    NOT NULL,
                sent_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                triggered_by   TEXT    NOT NULL DEFAULT 'cron'
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_route
                ON price_snapshots (origin, destination, departure_date);

            CREATE INDEX IF NOT EXISTS idx_notifications_route
                ON notifications_sent (origin, destination, departure_date);
        """)


def insert_price_snapshot(origin, destination, departure_date, price, currency,
                           airline=None, stops=0, deep_link=None, return_date=None):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO price_snapshots
                (origin, destination, departure_date, return_date, price, currency, airline, stops, deep_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (origin.upper(), destination.upper(), departure_date, return_date,
              price, currency.upper(), airline, stops, deep_link))


def get_previous_price(origin, destination, departure_date, return_date=None):
    """Return the most recent snapshot before today for this route/date."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT price, currency, fetched_at
            FROM price_snapshots
            WHERE origin = ?
              AND destination = ?
              AND departure_date = ?
              AND (return_date = ? OR (return_date IS NULL AND ? IS NULL))
            ORDER BY fetched_at DESC
            LIMIT 1
        """, (origin.upper(), destination.upper(), departure_date,
              return_date, return_date)).fetchone()
    return dict(row) if row else None


def get_cheapest_ever(origin, destination):
    """Return the lowest price ever recorded for a route regardless of date."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT price, currency, departure_date, return_date, airline, deep_link, fetched_at
            FROM price_snapshots
            WHERE origin = ? AND destination = ?
            ORDER BY price ASC
            LIMIT 1
        """, (origin.upper(), destination.upper())).fetchone()
    return dict(row) if row else None


def get_price_history(origin, destination, days=30):
    """Return all snapshots for a route over the last N days."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT departure_date, return_date, price, currency, airline, stops, fetched_at
            FROM price_snapshots
            WHERE origin = ? AND destination = ? AND fetched_at >= ?
            ORDER BY fetched_at DESC
        """, (origin.upper(), destination.upper(), since)).fetchall()
    return [dict(r) for r in rows]


def was_recently_notified(origin, destination, departure_date, return_date=None, within_hours=20):
    """True if a notification was already sent for this route/date in the last N hours."""
    since = (datetime.utcnow() - timedelta(hours=within_hours)).isoformat()
    with get_connection() as conn:
        row = conn.execute("""
            SELECT 1 FROM notifications_sent
            WHERE origin = ?
              AND destination = ?
              AND departure_date = ?
              AND (return_date = ? OR (return_date IS NULL AND ? IS NULL))
              AND sent_at >= ?
            LIMIT 1
        """, (origin.upper(), destination.upper(), departure_date,
              return_date, return_date, since)).fetchone()
    return row is not None


def insert_notification(origin, destination, departure_date, price, currency,
                         return_date=None, triggered_by="cron"):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO notifications_sent
                (origin, destination, departure_date, return_date, price, currency, triggered_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (origin.upper(), destination.upper(), departure_date,
              return_date, price, currency.upper(), triggered_by))


if __name__ == "__main__":
    init_db()
    print(f"Database initialised at {DB_PATH}")

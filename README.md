# OpenClaw Flight Tracker

A self-hosted flight price monitor running on a Raspberry Pi. Tracks configured routes daily and supports on-demand flight searches — all controlled via Telegram.

## How it works

- A cron job runs every morning at 08:00, fetches prices for your configured routes via SerpAPI, and sends a summary to your Telegram.
- OpenClaw (AI agent) runs on the Pi and handles conversational commands: add/remove routes, trigger manual checks, query price history, or search any ad-hoc flight.
- Prices are stored in SQLite so the bot can show trends and history over time.

## Stack

| Component | Tool | Cost |
|---|---|---|
| AI agent | [OpenClaw](https://openclaw.ai) + Google Gemini 2.0 Flash | Free |
| Messaging | Telegram Bot API | Free |
| Flight data | SerpAPI Google Flights | Free (250 calls/month) |
| Database | SQLite | Free |
| Scheduler | cron | — |
| Hardware | Raspberry Pi 2GB | — |

## File structure

```
open-claw/
├── AGENTS.md           # OpenClaw persistent instructions — auto-loaded every session
├── config.yaml         # Routes and settings — managed by the agent
├── db.py               # SQLite schema + query helpers
├── flights_client.py   # SerpAPI Google Flights wrapper
├── price_checker.py    # Cron script — fetches prices and sends Telegram daily summary
├── search_now.py       # Ad-hoc CLI search — called by OpenClaw for conversational queries
├── requirements.txt    # Python dependencies
├── .env                # API keys (not committed)
└── .gitignore
```

## Prerequisites

- Raspberry Pi running Raspberry Pi OS
- Node.js 22+
- Python 3
- A [SerpAPI](https://serpapi.com) account (free tier: 250 calls/month)
- A Telegram bot token (create one via [@BotFather](https://t.me/BotFather))
- A [Google AI Studio](https://aistudio.google.com) API key (Gemini free tier)

## Deployment to Raspberry Pi

**1. Install Node.js 22**
```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

**2. Install OpenClaw**
```bash
curl -fsSL https://openclaw.ai/install.sh | bash
```

**3. Onboard OpenClaw**
```bash
openclaw onboard --install-daemon
```
Set workspace to `/home/pi/open-claw` and choose Google/Gemini as the AI provider.

**4. Deploy project files**

Copy all files to `/home/pi/open-claw/` on the Pi.

**5. Install Python dependencies**
```bash
pip3 install -r requirements.txt
```

**6. Create `.env`**
```
SERPAPI_KEY=your_serpapi_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

**7. Initialise the database**
```bash
python3 db.py
```

**8. Set OpenClaw workspace**

In OpenClaw config, set:
```
agents.defaults.workspace: /home/pi/open-claw
```

**9. Add the cron job**
```bash
crontab -e
```
Add:
```
0 8 * * * cd /home/pi/open-claw && python3 price_checker.py >> /home/pi/open-claw/cron.log 2>&1
```

## Configuration

Routes and settings are managed in `config.yaml`. You can edit it directly or via Telegram commands to OpenClaw.

**Example route (round trip):**
```yaml
routes:
  - origin: CPH
    destination: WAW
    type: round_trip
    outbound_date_range:
      from: "2026-07-01"
      to: "2026-07-15"
    return_date_range:
      from: "2026-07-08"
      to: "2026-07-22"
    max_price: 1500
    currency: DKK
    max_stops: 1
    active: true
```

**Settings:**

| Key | Description | Default |
|---|---|---|
| `alert_mode` | `daily`, `immediate`, or `both` | `daily` |
| `price_drop_threshold_pct` | % drop that triggers an immediate alert | `10` |
| `max_samples_per_route` | Dates sampled per route per cron run | `3` |

## API call budget

SerpAPI free tier: **250 calls/month**.

At `max_samples_per_route: 3` with 2 active routes:
- 3 samples × 2 routes × 30 days ≈ **180 calls/month**

Adding more routes or raising samples will approach the limit. Either reduce `max_samples_per_route` or upgrade your SerpAPI plan.

## Telegram commands

Talk to your bot via OpenClaw on Telegram:

| Say... | What happens |
|---|---|
| `Add route CPH to LIS, round trip, July...` | New route added to config.yaml |
| `Remove CPH to WAW` | Route set to `active: false` |
| `Check prices now` | Runs price_checker.py immediately |
| `Cheapest flight to WAW ever?` | Queries SQLite price history |
| `Show price history CPH to WAW` | Returns last 30 days of prices |
| `How many API calls left?` | Estimates remaining SerpAPI budget |
| `Search CPH to GIG, July 1–15 outbound, up to 1 stop` | Ad-hoc one-off search via search_now.py |

## Database schema

**`price_snapshots`** — every price fetched:
- `origin`, `destination`, `departure_date`, `return_date`
- `price`, `currency`, `airline`, `stops`, `deep_link`, `fetched_at`

**`notifications_sent`** — log of every Telegram message:
- `triggered_by`: `cron`, `immediate_alert`, or `agent`

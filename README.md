# Hot Wheels Blinkit Agent

Checks Blinkit search results for Hot Wheels across configured Pune locations.

The agent has three pipeline stages:

- Scraper: gathers Blinkit stock by location.
- Collector classifier: tags each listing as grail, premium, real_car, maybe, common, or ignored.
- Curator: deduplicates locations, removes generic noise, and sends compact Telegram summaries.

## Setup on Windows

```powershell
cd C:\Users\soura\Documents\hotwheels_agent
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Configure

Edit `config.json`. For GitHub later, keep secrets out of committed files: `config.json` is ignored and `config.example.json` is the safe template.

- `locations`: names and latitude/longitude pairs to check.
- `collector.priority_keywords`: real-car brands/castings that should alert quickly.
- `collector.premium_keywords`: Premium, Car Culture, Boulevard, Team Transport, Treasure Hunt, etc.
- `exclude_castings` / `collector.ignore_keywords`: fantasy castings, generic packs, playsets, books, bikes, and other noise to skip.
- `collector.digest_max_priority_items` / `collector.digest_max_other_items`: keep Telegram short.
- `scraper.result_scrolls`: scroll passes after page load so Blinkit exposes more result batches.
- `telegram.bot_token`: token from BotFather.
- `telegram.chat_id`: your Telegram chat id.
- `telegram_alerts`: keeps Telegram compact with one image preview, one action button, and short top-pick/watchlist sections.
- `quiet_hours`: optional notification quiet window. Grails can still override it.
- `schedule.interval_minutes`: default is 60.
- `schedule.active_hours`: default is 06:00 to 00:00 Asia/Kolkata.
- `stock_digest_interval_minutes`: default is 240, so one digest every 4 hours.

Optional collector memory:

```powershell
copy collection.example.json collection.json
```

Edit `collection.json` to add castings you already own and wishlist priorities. Owned matches are filtered before alerts/digests. Wishlist matches can raise urgency without weakening existing collector rules.

You can also keep secrets out of `config.json` by setting:

```powershell
$env:TELEGRAM_BOT_TOKEN="123456:abc..."
$env:TELEGRAM_CHAT_ID="123456789"
$env:ANTHROPIC_API_KEY="sk-ant-..."
```

## Run

From Command Prompt:

```bat
cd C:\Users\soura\Documents\hotwheels_agent
python setup_check.py
python manual_trial.py
python main.py
```

If activation ever behaves oddly, these launchers always use the project venv directly:

```bat
setup_check.bat
trial_run.bat
run_agent.bat
```

`manual_trial.py` / `trial_run.bat` runs one check cycle, forces a stock digest, sends Telegram, and exits.

`main.py --once --ignore-active-hours` / `run_once.bat` runs one normal check cycle and exits, ignoring the active-hours window.

`main.py --once` / `run_hourly.bat` runs one scheduled check cycle and exits, respecting the active-hours window in `config.json`.

`main.py` / `run_agent.bat` starts the scheduler and keeps running.

`smoke_scrape.py` checks Blinkit and prints counts/picks without sending Telegram.

## Automation

Best local option on Windows:

```powershell
cd C:\Users\soura\Documents\hotwheels_agent
powershell -ExecutionPolicy Bypass -File .\install_windows_task.ps1
```

This installs a Task Scheduler job that runs `run_hourly.bat` once every hour. Each run checks all configured locations, sends alerts/digests if needed, updates `state.json`, and exits. The `schedule.active_hours` window in `config.json` still decides whether a given hourly run should actually scan or skip.

GitHub Actions option:

- Push this repo to GitHub.
- Add repository secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and optionally `ANTHROPIC_API_KEY`.
- The included workflow runs hourly from 08:00 to 00:00 Asia/Kolkata, forces a Telegram digest each run, and caches `state.json` so alert cooldowns survive between runs.

Useful options:

```bat
python main.py --help
python main.py --once --ignore-active-hours
python main.py --once --force-digest --ignore-active-hours
```

For first troubleshooting, set `scraper.headless` to `false` in `config.json` so you can watch the browser. The scraper writes candidate Blinkit API URLs to `api_hits.log`, and if no products are found it saves a screenshot and HTML under `debug/`.

## Telegram Chat ID

1. Create the bot with `@BotFather`.
2. Send any message to the bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates`.
4. Copy `message.chat.id` into `config.json`.

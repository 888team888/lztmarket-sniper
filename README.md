# 🔥 LZT Market Checker

> Monitor LZT Market listings in real time. Get instant Discord alerts when stock changes. Control everything from your phone.

**Python · Flask · Selenium · Mobile-first web UI**

---

## What it does

LZT Market Checker watches one or more LZT market search URLs and sends you a Discord notification the moment the stock changes — new listings appear, old ones disappear, or prices shift. You set it running on your PC and control it from any device on the same WiFi, including your iPhone.

**Key features:**

- Watch multiple market links simultaneously
- Per-link filters: min/max price, keyword matching
- Instant Discord embeds with offer details and @everyone pings on changes
- Live stock chart and scan history
- Pause individual links without stopping everything
- Trigger a manual scan on demand
- One-tap offer copy
- Browser push notifications when your tab is in the background
- Session survives page refreshes
- Chrome runs headless — no visible browser window

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.10+ | [python.org](https://python.org) |
| Google Chrome | Any recent version |
| ChromeDriver | Must match your Chrome version — see below |
| A Discord server | With webhook access |
| An LZT account | Logged in via Chrome |

---

## Setup — Step by Step

### Step 1 — Clone the repo

```bash
git clone https://github.com/yourusername/lzt-market-checker.git
cd lzt-market-checker
```

Or just [download the ZIP](../../archive/refs/heads/main.zip) and extract it.

---

### Step 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

If you get a permissions error on Windows, try:

```bash
pip install -r requirements.txt --user
```

---

### Step 3 — Set up ChromeDriver

ChromeDriver lets the tool control Chrome automatically. It must match your installed Chrome version exactly.

**Check your Chrome version:**
Open Chrome → address bar → type `chrome://version` → look at the first line, e.g. `120.0.6099.109`

**Download ChromeDriver:**
Go to [googlechromelabs.github.io/chrome-for-testing](https://googlechromelabs.github.io/chrome-for-testing/) and download the version that matches yours.

**Windows:** Extract `chromedriver.exe` and put it somewhere permanent, like `C:\chromedriver\chromedriver.exe`. Then add that folder to your PATH:
- Search "Environment Variables" in Start
- Edit `Path` under System Variables
- Add the folder path
- Click OK and restart your terminal

**Test it works:**
```bash
chromedriver --version
```
Should print your version number.

---

### Step 4 — Create a Chrome profile for LZT

The tool needs to be logged into LZT inside Chrome. We create a separate profile so it doesn't interfere with your main browser.

Open a terminal and run:

```bash
# Windows
chrome.exe --user-data-dir="C:\Users\YOUR_USERNAME\selenium-lzt-profile"

# Mac
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --user-data-dir="/Users/YOUR_USERNAME/selenium-lzt-profile"
```

A fresh Chrome window opens. Log into your LZT account normally, solve any captchas, then **close this Chrome window**.

---

### Step 5 — Configure the app

Open `app.py` in any text editor. Near the top you'll see:

```python
PROFILE_PATH = r"C:\Users\anast\selenium-lzt-profile"
```

Change `anast` to your actual Windows username. If you used a different path in Step 4, use that path here.

**Mac/Linux users** — remove the `r` prefix and use forward slashes:

```python
PROFILE_PATH = "/Users/yourusername/selenium-lzt-profile"
```

---

### Step 6 — Create a Discord webhook

1. Open your Discord server
2. Go to the channel you want alerts in
3. Click the gear icon (Edit Channel) → Integrations → Webhooks
4. Click **New Webhook** → Copy Webhook URL
5. Keep this URL safe — you'll paste it into the app UI

---

### Step 7 — Run the app

```bash
python app.py
```

You'll see:

```
LZT Market Multi-Checker v2
─────────────────────────────
Run 'ipconfig' in cmd, look for IPv4 under Wi-Fi
Then open  http://<that-ip>:5000  in Safari
```

Open a browser on the **same device** and go to:
```
http://127.0.0.1:5000
```

It works. The checker is running.

---

## Accessing from your iPhone

This is the killer feature. Your PC runs the server, your phone is the remote control.

**1. Find your PC's local IP address:**

Open Command Prompt (`Win+R` → type `cmd` → Enter) and run:
```
ipconfig
```

Look for **"Wireless LAN adapter Wi-Fi"** and find the **IPv4 Address**, e.g.:
```
IPv4 Address. . . . . . . . . . . : 192.168.1.42
```

**2. Make sure your iPhone is on the same WiFi network as your PC.**

**3. Open Safari on your iPhone and type:**
```
http://192.168.1.42:5000
```

The full UI loads in your browser. Everything works — start/stop, live log, notifications, offers, chart.

**4. Add to your Home Screen (optional but recommended):**
- Tap the Share button (box with arrow) in Safari
- Tap **"Add to Home Screen"**
- Give it a name like "LZT Checker"
- Tap **Add**

Now it works like an app — full screen, no address bar, instant access from your home screen.

---

## How to use it

### Adding links

Go to the **Links** tab. You'll see one link slot by default. Click **+ Add Link** to add more.

For each link:

| Field | What to put |
|---|---|
| URL | The LZT market search URL (copy from your browser) |
| Label | A short name shown in the dashboard, e.g. "Korblox cheap" |
| Min price | Only alert if an offer is above this price |
| Max price | Only alert if an offer is below this price |
| Keywords | Comma-separated words that must all appear in the offer text |

**Finding good LZT URLs:**
Go to lzt.market, search for what you want, apply filters (price range, game, etc.), then copy the URL from your address bar. That's what goes in the URL field.

Example URLs:
```
https://lzt.market/roblox/?pmax=89&title=korblox
https://lzt.market/steam/?pmin=5&pmax=50
https://lzt.market/fortnite/
```

### Starting the checker

1. Fill in your Discord webhook
2. Set your check interval (minimum 1 minute — be respectful to the site)
3. Click **▶ Start Checker**

The dashboard tab opens automatically showing live stats.

### Dashboard

- **Stat cards** — watching count, total scans, changes found, total stock — update every 6 seconds
- **Stock chart** — shows stock count over time for the selected URL
- **Live stock** — one row per link with current offer count and action buttons

**Action buttons on each row:**
- ⟳ — trigger an immediate scan of just this link
- ⏸ — pause this link (skips it during the next cycle, does not stop others)
- 👁 — jump to the Offers tab for this link

### Offers tab

Shows the current offer text for any watched link. Tap **Copy** on any offer to copy the full text to your clipboard — useful for forwarding to someone or keeping notes.

### History tab

A table of every scan, showing the time, link label, offer count, and whether anything changed. Newest first. Tap **Refresh** to reload.

### Notifications

Tap the 🔔 button in the top-right of the dashboard and allow notifications when your browser asks. After that:
- When stock changes, a toast notification slides up from the bottom of the screen
- If Safari is in the background or your screen is off, you get a system push notification

---

## Discord alerts

Every time stock changes you get an embed like this:

```
🟢 LZT Market — Stock Update
Stock increased: 3 → 5
Filters: max $89 | korblox

[Open search page]

🛒 Offer #1
[offer text]

🛒 Offer #2
[offer text]
...

Stock: 5 | LZT Multi-Checker v2
```

- 🟢 green = stock went up (ping @everyone)
- 🔴 red = stock went down (ping @everyone)
- 🟡 yellow = offers changed but count is the same (ping @everyone)
- 🔵 blue = initial scan (no ping)

---

## Troubleshooting

**`selenium.common.exceptions.WebDriverException: chromedriver` not found**
ChromeDriver is not in your PATH. See Step 3. Make sure `chromedriver --version` works in a fresh terminal.

**Page loads but shows "No accounts found" immediately**
The Chrome profile isn't logged into LZT. Redo Step 4 and make sure you actually log in before closing Chrome.

**`TemplateNotFound: index.html`**
You have an old version of the app with a separate templates folder. Download the latest `app.py` — everything is in one file now.

**Can't reach the app from iPhone**
- Make sure your phone and PC are on the same WiFi network (not one on 5GHz and one on 2.4GHz with different SSIDs)
- Make sure Windows Firewall isn't blocking port 5000. You may see a popup asking to allow it — click Allow.
- Double-check the IP from `ipconfig` — it can change when you reconnect to WiFi

**App works but Discord gets no messages**
- Check the webhook URL is correct — it should start with `https://discord.com/api/webhooks/`
- Make sure the webhook channel still exists and hasn't been deleted
- Check the terminal for any error lines starting with `requests.exceptions`

**Offers look wrong or duplicated**
The scraper looks for elements containing "followers" in the text. If LZT changes their DOM structure this may break. Open an issue with the URL and we'll fix the selector.

---

## API reference

The Flask server exposes these endpoints — useful if you want to build your own interface or automate things.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the web UI |
| `POST` | `/api/start` | Start the checker. Body: `{link_configs, webhook, interval}` |
| `POST` | `/api/stop` | Stop all checking |
| `POST` | `/api/pause` | Toggle pause for one URL. Body: `{url}` |
| `POST` | `/api/scan_now` | Trigger immediate scan. Body: `{url}` |
| `GET` | `/api/status` | Current state: running, stock, paused URLs, config |
| `GET` | `/api/history` | Array of all scan history entries |
| `GET` | `/api/offers?url=...` | Current offer list for a URL |
| `GET` | `/api/stream` | SSE stream of log events and notifications |

---

## Project structure

```
lzt-market-checker/
├── app.py                  # Everything — Flask server + web UI (single file)
├── requirements.txt        # Python dependencies
├── CHANGELOG.md            # Version history
├── CONTRIBUTING.md         # How to contribute
├── LICENSE                 # MIT
├── .gitignore
└── .github/
    └── ISSUE_TEMPLATE/
        ├── bug_report.md
        └── feature_request.md
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — do whatever you want with it, just don't remove the license.

---

## Disclaimer

This tool is for personal use to monitor publicly visible market listings. Use it responsibly — don't set the interval below 1 minute, don't run hundreds of links in parallel, and don't use it to do anything that violates LZT's terms of service.

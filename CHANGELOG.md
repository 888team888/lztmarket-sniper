# Changelog

All notable changes to this project will be documented here.

---

## [2.0.0] — 2026

### Added
- Full web UI — control from any device on the same WiFi (iPhone, tablet, PC)
- 4-tab interface: Dashboard, Links, Offers, History
- Per-link filters: min price, max price, keyword matching
- Live stock chart — canvas-drawn, no external JS libraries
- Stat cards: watching count, total scans, changes found, total stock
- Per-link pause/resume without stopping the whole checker
- Per-link instant scan (trigger a single check on demand)
- One-tap offer copy in the Offers tab
- Toast notifications — slide-up alerts on every stock change
- Browser push notifications — system alerts when tab is in background
- Full scan history table with change detection markers
- Session restore — page refresh reconnects automatically
- SSE (Server-Sent Events) log stream — live log on any device
- Chrome runs headless — no visible browser window on PC
- Single-file deployment — no templates folder required

### Changed
- Replaced tkinter desktop app with Flask web server
- Stock tracking is now per-URL with independent state
- Discord embeds now include active filter details

---

## [1.0.0] — 2025

### Added
- Initial tkinter desktop app
- Single URL monitoring
- Discord webhook embed alerts with @everyone ping on changes
- Offer deduplication via Selenium DOM scraping
- Configurable check interval
- Activity log with timestamps
- Color-coded Discord embeds (green/red/yellow/blue)

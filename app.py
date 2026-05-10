"""
LZT Market Multi-Checker — v2  (single file, no templates folder)
Run:   python app.py
Open:  http://<your-pc-ip>:5000  in Safari on same WiFi
"""

import time, re, threading, queue, json, collections
import requests as req_lib
from flask import Flask, request, jsonify, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

# ── EDIT THIS ──────────────────────────────────────────────────────────────────
PROFILE_PATH = r"C:\Users\anast\selenium-lzt-profile"
# ───────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)

state = {
    "running":          False,
    "paused_urls":      set(),          # urls currently paused
    "last_offers_map":  {},             # url -> list[str]
    "scan_history":     collections.deque(maxlen=200),  # {ts, url, count, changed}
    "total_scans":      0,
    "total_changes":    0,
    "thread":           None,
    "config":           {},             # saved from last start
}
log_queue  = queue.Queue()
push_queue = queue.Queue()             # browser push events


# ── helpers ────────────────────────────────────────────────────────────────────

def clean_text(text):
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

def push_log(msg, tag="info"):
    entry = {"ts": time.strftime("%H:%M:%S"), "msg": msg, "tag": tag, "type": "log"}
    log_queue.put(entry)

def push_event(kind, data):
    push_queue.put({"type": kind, **data})


# ── discord ────────────────────────────────────────────────────────────────────

def send_discord_embed(webhook, url, offers, change_text, ping=False, min_price=None, max_price=None, keywords=None):
    stock = len(offers)
    if "increased" in change_text:   color, emoji = 0x2ecc71, "🟢"
    elif "decreased" in change_text: color, emoji = 0xe74c3c, "🔴"
    elif "changed" in change_text:   color, emoji = 0xf1c40f, "🟡"
    else:                            color, emoji = 0x3498db, "🔵"

    fields = []
    if stock == 0:
        fields.append({"name": "No accounts found", "value": "No matching offers currently listed.", "inline": False})
    else:
        for i, offer in enumerate(offers[:6], 1):
            short = offer[:800] + "..." if len(offer) > 800 else offer
            fields.append({"name": f"Offer #{i}", "value": f"```{short}```", "inline": False})

    filters_desc = []
    if min_price is not None: filters_desc.append(f"min ${min_price}")
    if max_price is not None: filters_desc.append(f"max ${max_price}")
    if keywords:              filters_desc.append(f"kw: {', '.join(keywords)}")
    filter_line = f"\nFilters: {' | '.join(filters_desc)}" if filters_desc else ""

    req_lib.post(webhook, json={
        "content": "@everyone" if ping else "",
        "embeds": [{
            "title": f"{emoji} LZT Market — Stock Update",
            "description": f"**{change_text}**{filter_line}\n\n[Open search page]({url})",
            "color": color, "fields": fields,
            "footer": {"text": f"Stock: {stock} | LZT Multi-Checker v2"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }],
        "allowed_mentions": {"parse": ["everyone"] if ping else []},
    }, timeout=15)


# ── selenium ───────────────────────────────────────────────────────────────────

def check_offers(url):
    options = Options()
    options.add_argument(f"--user-data-dir={PROFILE_PATH}")
    options.add_argument("--window-size=1600,1000")
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        WebDriverWait(driver, 30).until(
            lambda d: "followers" in d.execute_script("return document.body.innerText")
            or "No accounts found" in d.execute_script("return document.body.innerText")
        )
        if "No accounts found" in driver.execute_script("return document.body.innerText"):
            return []
        offers = driver.execute_script("""
            const all=[...document.querySelectorAll("div,li,article")];
            function visible(el){
                const r=el.getBoundingClientRect(),s=window.getComputedStyle(el);
                return r.width>0&&r.height>0&&s.display!=="none"&&s.visibility!=="hidden";
            }
            const cards=all.filter(el=>{
                const t=el.innerText||"";
                return visible(el)&&/followers/i.test(t)&&t.length>40&&t.length<2000;
            });
            const out=[];
            for(const c of cards){
                const t=c.innerText||"";
                if(t.split("\\n").length>80) continue;
                if(out.some(e=>e.innerText===c.innerText)) continue;
                if(out.some(e=>e.contains(c))) continue;
                out.push(c);
            }
            return out.map(c=>c.innerText);
        """)
        cleaned, seen = [], set()
        for offer in offers:
            offer = clean_text(offer)
            if offer and offer not in seen:
                seen.add(offer); cleaned.append(offer)
        return cleaned
    finally:
        driver.quit()


def filter_offers(offers, min_price=None, max_price=None, keywords=None):
    """Client-side post-filter on returned offers."""
    result = []
    for offer in offers:
        # price filter: look for numbers preceded by $ or followed by $
        if min_price is not None or max_price is not None:
            prices = re.findall(r'\$?\s*(\d+(?:\.\d+)?)', offer)
            if prices:
                p = float(prices[0])
                if min_price is not None and p < min_price: continue
                if max_price is not None and p > max_price: continue
        # keyword filter: all keywords must appear (case-insensitive)
        if keywords:
            lower = offer.lower()
            if not all(kw.lower() in lower for kw in keywords): continue
        result.append(offer)
    return result


def get_change_text(offers, old):
    n = len(offers)
    if old is None: return f"Initial scan - {n} offer(s) found"
    o = len(old)
    if n > o: return f"Stock increased: {o} to {n}"
    if n < o: return f"Stock decreased: {o} to {n}"
    return f"Offers changed, stock still {n}"


# ── bot loop ───────────────────────────────────────────────────────────────────

def bot_loop(urls, webhook, interval_seconds, link_configs):
    """
    link_configs: list of dicts per url:
      { url, min_price, max_price, keywords, label }
    """
    state["last_offers_map"].clear()
    push_log(f"Started — watching {len(urls)} link(s) every {interval_seconds//60} min.", "ok")

    while state["running"]:
        for cfg in link_configs:
            url = cfg["url"]
            if not state["running"]: break
            if url in state["paused_urls"]:
                push_log(f"Skipping (paused): {url[:50]}...", "warn")
                continue
            try:
                short = (url[:55] + "...") if len(url) > 55 else url
                push_log(f"Checking: {short}")
                raw_offers = check_offers(url)

                # apply per-link filters
                offers = filter_offers(
                    raw_offers,
                    min_price=cfg.get("min_price"),
                    max_price=cfg.get("max_price"),
                    keywords=cfg.get("keywords"),
                )

                old = state["last_offers_map"].get(url)
                changed = (old is None) or (set(offers) != set(old))

                state["total_scans"] += 1
                state["scan_history"].append({
                    "ts":      time.strftime("%H:%M:%S"),
                    "url":     url,
                    "label":   cfg.get("label") or short,
                    "count":   len(offers),
                    "changed": changed and old is not None,
                })

                if changed:
                    change_text = get_change_text(offers, old)
                    ping = (old is not None)
                    send_discord_embed(
                        webhook, url, offers, change_text, ping=ping,
                        min_price=cfg.get("min_price"),
                        max_price=cfg.get("max_price"),
                        keywords=cfg.get("keywords"),
                    )
                    state["last_offers_map"][url] = offers
                    if old is not None:
                        state["total_changes"] += 1
                    tag = "ok" if "increased" in change_text else "warn" if "decreased" in change_text else "info"
                    push_log(f"  -> {change_text}", tag)

                    # push browser notification event
                    push_event("notify", {
                        "title": change_text,
                        "body":  cfg.get("label") or short,
                        "tag":   tag,
                        "offers": offers[:3],
                    })
                else:
                    push_log(f"  -> No change. Stock: {len(offers)}")

            except Exception as exc:
                push_log(f"  -> Error: {exc}", "err")

        for _ in range(interval_seconds):
            if not state["running"]: break
            time.sleep(1)

    push_log("Checker stopped.", "warn")


# ── routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML

@app.route("/api/start", methods=["POST"])
def api_start():
    if state["running"]:
        return jsonify({"ok": False, "error": "Already running"})
    data = request.json

    # link_configs: list of {url, label, min_price, max_price, keywords}
    link_configs = data.get("link_configs", [])
    if not link_configs:
        # fallback: plain url list
        urls = [u.strip() for u in (data.get("urls") or "").splitlines() if u.strip()]
        link_configs = [{"url": u, "label": "", "min_price": None, "max_price": None, "keywords": []} for u in urls]

    webhook = (data.get("webhook") or "").strip()
    try: interval_minutes = max(1, int(data.get("interval", 3)))
    except: interval_minutes = 3

    if not link_configs: return jsonify({"ok": False, "error": "No URLs provided"})
    if not webhook:      return jsonify({"ok": False, "error": "No webhook provided"})

    urls = [c["url"] for c in link_configs]
    state["running"]       = True
    state["paused_urls"]   = set()
    state["config"]        = {"link_configs": link_configs, "webhook": webhook, "interval": interval_minutes}
    state["total_scans"]   = 0
    state["total_changes"] = 0
    state["scan_history"]  = collections.deque(maxlen=200)

    t = threading.Thread(target=bot_loop, args=(urls, webhook, interval_minutes * 60, link_configs), daemon=True)
    state["thread"] = t
    t.start()
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    state["running"] = False
    return jsonify({"ok": True})

@app.route("/api/pause", methods=["POST"])
def api_pause():
    url = (request.json or {}).get("url", "")
    if url in state["paused_urls"]:
        state["paused_urls"].discard(url)
        return jsonify({"ok": True, "paused": False})
    else:
        state["paused_urls"].add(url)
        return jsonify({"ok": True, "paused": True})

@app.route("/api/scan_now", methods=["POST"])
def api_scan_now():
    """Trigger an immediate rescan of one URL."""
    if not state["running"]:
        return jsonify({"ok": False, "error": "Not running"})
    url = (request.json or {}).get("url", "")
    cfg = next((c for c in state["config"].get("link_configs", []) if c["url"] == url), None)
    if not cfg:
        return jsonify({"ok": False, "error": "URL not found"})
    def _scan():
        try:
            push_log(f"Manual scan: {url[:55]}...")
            raw = check_offers(url)
            offers = filter_offers(raw, cfg.get("min_price"), cfg.get("max_price"), cfg.get("keywords"))
            old = state["last_offers_map"].get(url)
            change_text = get_change_text(offers, old)
            state["last_offers_map"][url] = offers
            push_log(f"  -> {change_text}", "ok")
            push_event("notify", {"title": change_text, "body": url[:55], "tag": "ok", "offers": offers[:3]})
        except Exception as e:
            push_log(f"  -> Manual scan error: {e}", "err")
    threading.Thread(target=_scan, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/status")
def api_status():
    return jsonify({
        "running":       state["running"],
        "paused_urls":   list(state["paused_urls"]),
        "stock":         {url: len(offers) for url, offers in state["last_offers_map"].items()},
        "total_scans":   state["total_scans"],
        "total_changes": state["total_changes"],
        "config":        state["config"],
    })

@app.route("/api/history")
def api_history():
    return jsonify(list(state["scan_history"]))

@app.route("/api/offers")
def api_offers():
    url = request.args.get("url", "")
    offers = state["last_offers_map"].get(url, [])
    return jsonify(offers)

@app.route("/api/stream")
def api_stream():
    """SSE — merges log_queue and push_queue."""
    def generate():
        while True:
            sent = False
            for q in (log_queue, push_queue):
                try:
                    entry = q.get_nowait()
                    yield f"data: {json.dumps(entry)}\n\n"
                    sent = True
                except queue.Empty:
                    pass
            if not sent:
                time.sleep(0.4)
                yield 'data: {"type":"ping"}\n\n'
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── HTML ───────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0d1117">
<title>LZT Checker</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap');
:root{
  --bg:#0d1117;--s1:#161b22;--s2:#21262d;--s3:#2d333b;
  --border:#30363d;--accent:#f78166;--green:#3fb950;--red:#f85149;
  --yellow:#d29922;--blue:#58a6ff;--purple:#bc8cff;
  --text:#e6edf3;--muted:#8b949e;--r:10px;
  --mono:'JetBrains Mono',monospace;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:var(--mono);background:var(--bg);color:var(--text);
  min-height:100dvh;overscroll-behavior:none;
  padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)}

/* ── NAV TABS ── */
.tab-bar{position:sticky;top:0;z-index:100;background:var(--bg);
  border-bottom:1px solid var(--border);display:flex;padding:0 12px}
.tab{flex:1;padding:14px 4px 12px;font-size:.72rem;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;color:var(--muted);border:none;background:none;
  cursor:pointer;border-bottom:2px solid transparent;transition:all .2s;
  font-family:var(--mono);-webkit-tap-highlight-color:transparent}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-content{display:none}.tab-content.active{display:block}
.shell{max-width:680px;margin:0 auto;padding:16px 14px 60px}

/* ── CARDS / INPUTS ── */
.card{background:var(--s1);border:1px solid var(--border);border-radius:var(--r);
  padding:16px 14px;margin-bottom:12px}
label{display:block;font-size:.7rem;font-weight:700;color:var(--muted);
  letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px}
input,textarea,select{width:100%;background:var(--s2);border:1px solid var(--border);
  border-radius:6px;color:var(--text);font-family:var(--mono);font-size:.82rem;
  padding:9px 11px;outline:none;transition:border-color .15s;-webkit-appearance:none}
input:focus,textarea:focus,select:focus{border-color:var(--accent)}
textarea{resize:vertical;min-height:80px}
select option{background:var(--s2)}

/* ── BUTTONS ── */
.btn{font-family:var(--mono);font-size:.8rem;font-weight:700;border:none;
  border-radius:7px;padding:11px 16px;cursor:pointer;
  transition:opacity .15s,transform .1s;letter-spacing:.04em;
  -webkit-tap-highlight-color:transparent;white-space:nowrap}
.btn:active{transform:scale(.96)}
.btn:disabled{opacity:.35;cursor:not-allowed}
.btn-green{background:#1a7f37;color:#fff}.btn-green:not(:disabled):hover{background:#238636}
.btn-red{background:#6e2020;color:#fff}.btn-red:not(:disabled):hover{background:#b62324}
.btn-ghost{background:var(--s3);color:var(--text);border:1px solid var(--border)}
.btn-ghost:hover{background:var(--s2)}
.btn-icon{background:var(--s3);border:1px solid var(--border);border-radius:6px;
  padding:7px 10px;cursor:pointer;font-size:.85rem;transition:all .15s;
  -webkit-tap-highlight-color:transparent}
.btn-icon:hover{background:var(--s2)}

/* ── STATUS PILL ── */
.pill{display:inline-flex;align-items:center;gap:6px;background:var(--s2);
  border:1px solid var(--border);border-radius:99px;padding:4px 12px;
  font-size:.72rem;font-weight:700;letter-spacing:.05em}
.dot{width:7px;height:7px;border-radius:50%;background:var(--red);flex-shrink:0}
.dot.live{background:var(--green);animation:pulse 1.8s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* ── STAT GRID ── */
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px}
.stat{background:var(--s1);border:1px solid var(--border);border-radius:var(--r);
  padding:14px 12px}
.stat-label{font-size:.67rem;font-weight:700;color:var(--muted);letter-spacing:.08em;
  text-transform:uppercase;margin-bottom:6px}
.stat-value{font-size:1.5rem;font-weight:700;color:var(--text)}
.stat-value.green{color:var(--green)}.stat-value.blue{color:var(--blue)}
.stat-value.yellow{color:var(--yellow)}.stat-value.purple{color:var(--purple)}

/* ── LINK BUILDER ── */
.link-entry{background:var(--s2);border:1px solid var(--border);border-radius:8px;
  padding:12px;margin-bottom:8px;position:relative}
.link-entry-header{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.link-num{background:var(--accent);color:#000;border-radius:4px;padding:1px 7px;
  font-size:.72rem;font-weight:700;flex-shrink:0}
.link-url-input{flex:1;min-width:0}
.link-filters{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
.link-filters input{font-size:.78rem;padding:7px 9px}
.remove-btn{background:var(--red);color:#fff;border:none;border-radius:5px;
  width:26px;height:26px;cursor:pointer;font-size:.85rem;flex-shrink:0;
  display:flex;align-items:center;justify-content:center}

/* ── STOCK ROWS ── */
.stock-row{display:flex;align-items:center;gap:8px;background:var(--s2);
  border:1px solid var(--border);border-radius:7px;padding:10px 12px;
  margin-bottom:8px;flex-wrap:wrap}
.stock-label{font-size:.78rem;color:var(--muted);flex:1;min-width:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.stock-badge{font-weight:700;font-size:.8rem;background:var(--s1);
  border:1px solid var(--border);border-radius:5px;padding:2px 8px;
  color:var(--blue);white-space:nowrap}
.stock-badge.up{color:var(--green)}.stock-badge.down{color:var(--red)}
.stock-actions{display:flex;gap:6px;flex-shrink:0}
.paused-badge{background:var(--yellow);color:#000;border-radius:4px;
  padding:1px 6px;font-size:.67rem;font-weight:700}

/* ── LOG ── */
.log-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.log-title{font-size:.7rem;font-weight:700;color:var(--muted);
  letter-spacing:.08em;text-transform:uppercase}
#log-box{background:#010409;border:1px solid var(--border);border-radius:8px;
  padding:11px;height:280px;overflow-y:auto;font-size:.77rem;line-height:1.75;
  -webkit-overflow-scrolling:touch}
.log-line{display:flex;gap:8px}
.log-ts{color:var(--border);flex-shrink:0;user-select:none}
.log-info{color:var(--text)}.log-ok{color:var(--green)}
.log-warn{color:var(--yellow)}.log-err{color:var(--red)}
#log-box::-webkit-scrollbar{width:3px}
#log-box::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* ── OFFERS PANEL ── */
.offer-card{background:var(--s2);border:1px solid var(--border);border-radius:7px;
  padding:11px 12px;margin-bottom:8px;font-size:.77rem;line-height:1.6;
  white-space:pre-wrap;word-break:break-word;position:relative}
.offer-copy{position:absolute;top:8px;right:8px;background:var(--s3);
  border:1px solid var(--border);border-radius:5px;padding:3px 8px;
  font-size:.68rem;cursor:pointer;color:var(--muted);transition:all .15s}
.offer-copy:hover{color:var(--text);border-color:var(--muted)}
.offer-copy.copied{color:var(--green);border-color:var(--green)}

/* ── CHART ── */
#chart-wrap{background:var(--s1);border:1px solid var(--border);border-radius:var(--r);
  padding:14px;margin-bottom:12px}
canvas#chart{width:100%;height:160px}

/* ── HISTORY TABLE ── */
.hist-row{display:flex;gap:8px;font-size:.72rem;padding:5px 0;
  border-bottom:1px solid var(--border);align-items:center}
.hist-ts{color:var(--muted);flex-shrink:0;width:52px}
.hist-label{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)}
.hist-count{color:var(--blue);flex-shrink:0;width:28px;text-align:right;font-weight:700}
.hist-changed{color:var(--yellow);font-size:.67rem;flex-shrink:0}

/* ── NOTIF TOAST ── */
#toast-wrap{position:fixed;bottom:calc(env(safe-area-inset-bottom)+20px);
  left:50%;transform:translateX(-50%);z-index:9999;width:calc(100% - 32px);
  max-width:440px;pointer-events:none}
.toast{background:var(--s2);border:1px solid var(--border);border-radius:9px;
  padding:11px 14px;margin-top:8px;font-size:.8rem;display:flex;gap:10px;
  align-items:flex-start;animation:slideup .25s ease;pointer-events:auto}
@keyframes slideup{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.toast.fade{animation:fadeout .4s ease forwards}
@keyframes fadeout{to{opacity:0;transform:translateY(8px)}}
.toast-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:4px}
.toast-body{flex:1;min-width:0}
.toast-title{font-weight:700;margin-bottom:2px}
.toast-sub{color:var(--muted);font-size:.72rem;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}

/* ── MISC ── */
.section-label{font-size:.7rem;font-weight:700;color:var(--muted);
  letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px}
.empty{color:var(--muted);font-size:.8rem;text-align:center;padding:18px 0}
.row{display:flex;gap:8px;align-items:center}
.row.wrap{flex-wrap:wrap}
.gap-top{margin-top:12px}
.gap-bot{margin-bottom:12px}
.text-muted{color:var(--muted);font-size:.78rem}
.text-green{color:var(--green)}.text-red{color:var(--red)}.text-yellow{color:var(--yellow)}
.full{width:100%}
hr{border:none;border-top:1px solid var(--border);margin:14px 0}
</style>
</head>
<body>

<!-- ── TAB BAR ── -->
<div class="tab-bar">
  <button class="tab active" onclick="switchTab('dashboard')">Dashboard</button>
  <button class="tab" onclick="switchTab('links')">Links</button>
  <button class="tab" onclick="switchTab('offers')">Offers</button>
  <button class="tab" onclick="switchTab('history')">History</button>
</div>

<!-- ════════════════ DASHBOARD TAB ════════════════ -->
<div id="tab-dashboard" class="tab-content active">
<div class="shell">

  <!-- header -->
  <div class="row" style="margin:4px 0 16px;flex-wrap:wrap;gap:10px">
    <div>
      <span style="font-size:1.2rem;font-weight:700;color:var(--accent)">LZT</span>
      <span style="font-size:.85rem;color:var(--muted)"> // checker v2</span>
    </div>
    <div class="pill" id="status-pill">
      <div class="dot" id="status-dot"></div>
      <span id="status-label">STOPPED</span>
    </div>
    <button class="btn-icon" onclick="requestNotifPerm()" title="Enable notifications" id="notif-btn">🔔</button>
  </div>

  <!-- stats -->
  <div class="stat-grid">
    <div class="stat">
      <div class="stat-label">Watching</div>
      <div class="stat-value blue" id="stat-watching">0</div>
    </div>
    <div class="stat">
      <div class="stat-label">Total Scans</div>
      <div class="stat-value purple" id="stat-scans">0</div>
    </div>
    <div class="stat">
      <div class="stat-label">Changes Found</div>
      <div class="stat-value yellow" id="stat-changes">0</div>
    </div>
    <div class="stat">
      <div class="stat-label">Total Stock</div>
      <div class="stat-value green" id="stat-stock">0</div>
    </div>
  </div>

  <!-- chart -->
  <div id="chart-wrap">
    <div class="row" style="margin-bottom:10px">
      <span class="section-label" style="margin:0">Stock over time</span>
      <select id="chart-url-sel" onchange="redrawChart()" style="flex:1;margin-left:10px;font-size:.72rem;padding:4px 8px"></select>
    </div>
    <canvas id="chart"></canvas>
    <div class="empty" id="chart-empty" style="display:none">No scan history yet</div>
  </div>

  <!-- live stock -->
  <div class="section-label">Live stock</div>
  <div id="stock-grid"><div class="empty">Start the checker to see stock</div></div>

  <!-- controls -->
  <div class="row wrap gap-top">
    <button class="btn btn-green full" id="btn-start" onclick="gotoLinks()">Configure &amp; Start</button>
    <button class="btn btn-red" id="btn-stop" onclick="stopChecker()" disabled style="flex:1">Stop All</button>
  </div>

</div>
</div>

<!-- ════════════════ LINKS TAB ════════════════ -->
<div id="tab-links" class="tab-content">
<div class="shell">

  <div class="row" style="margin-bottom:12px;flex-wrap:wrap;gap:8px">
    <span class="section-label" style="margin:0;flex:1">Market Links</span>
    <button class="btn btn-ghost" onclick="addLink()">+ Add Link</button>
  </div>

  <div id="link-list"></div>

  <hr>

  <div class="card">
    <label>Discord Webhook</label>
    <input type="password" id="webhook" placeholder="https://discord.com/api/webhooks/...">
    <div style="margin-top:10px">
      <label>Check Interval (minutes)</label>
      <input type="number" id="interval" value="3" min="1" max="60" style="width:100px">
    </div>
  </div>

  <div class="row wrap">
    <button class="btn btn-green full" id="btn-start-links" onclick="startChecker()">&#9654; Start Checker</button>
  </div>
  <div class="text-muted gap-top" id="start-error" style="color:var(--red)"></div>

</div>
</div>

<!-- ════════════════ OFFERS TAB ════════════════ -->
<div id="tab-offers" class="tab-content">
<div class="shell">

  <div class="row" style="margin-bottom:12px;flex-wrap:wrap;gap:8px">
    <span class="section-label" style="margin:0">Current Offers</span>
    <select id="offers-url-sel" onchange="loadOffers()" style="flex:1;font-size:.72rem;padding:5px 8px"></select>
  </div>
  <div id="offers-list"><div class="empty">Select a link to see its offers</div></div>

</div>
</div>

<!-- ════════════════ HISTORY TAB ════════════════ -->
<div id="tab-history" class="tab-content">
<div class="shell">

  <div class="row" style="margin-bottom:12px;flex-wrap:wrap;gap:8px">
    <span class="section-label" style="margin:0">Scan History</span>
    <button class="btn btn-ghost" onclick="loadHistory()" style="font-size:.72rem;padding:6px 10px">Refresh</button>
  </div>

  <div class="card" style="padding:0 0 0 0;overflow:hidden">
    <div class="row" style="padding:10px 12px;border-bottom:1px solid var(--border)">
      <span style="font-size:.7rem;color:var(--muted);flex-shrink:0;width:52px">TIME</span>
      <span style="font-size:.7rem;color:var(--muted);flex:1">LINK</span>
      <span style="font-size:.7rem;color:var(--muted);width:28px;text-align:right">CNT</span>
      <span style="font-size:.7rem;color:var(--muted);width:50px;text-align:right">CHG</span>
    </div>
    <div id="history-list" style="max-height:60vh;overflow-y:auto;padding:0 12px">
      <div class="empty">No history yet</div>
    </div>
  </div>

</div>
</div>

<!-- ── log (always visible at bottom of dashboard) ── -->
<div id="tab-log-wrap" style="max-width:680px;margin:0 auto;padding:0 14px 30px;display:none">
  <div class="card" style="margin:0">
    <div class="log-header">
      <span class="log-title">Activity Log</span>
      <div class="row" style="gap:6px">
        <button class="btn-icon" onclick="clearLog()" style="font-size:.72rem;padding:4px 8px">Clear</button>
        <button class="btn-icon" onclick="toggleLog()" id="log-toggle" style="font-size:.72rem;padding:4px 8px">Hide</button>
      </div>
    </div>
    <div id="log-box"></div>
  </div>
</div>

<!-- ── toast container ── -->
<div id="toast-wrap"></div>

<script>
// ══════════════════════════════════════════════════════════
// STATE
// ══════════════════════════════════════════════════════════
let evtSource = null;
let chartData  = {};   // url -> [{ts, count}]
let linkCount  = 0;
let notifGranted = Notification && Notification.permission === 'granted';

// ══════════════════════════════════════════════════════════
// TABS
// ══════════════════════════════════════════════════════════
function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t,i)=>{
    const tabs = ['dashboard','links','offers','history'];
    t.classList.toggle('active', tabs[i]===name);
  });
  document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  if (name==='history') loadHistory();
  if (name==='offers')  syncOfferSel();
}

function gotoLinks() { switchTab('links'); }

// ══════════════════════════════════════════════════════════
// LINK BUILDER
// ══════════════════════════════════════════════════════════
function addLink(url='', label='', minP='', maxP='', keywords='') {
  linkCount++;
  const n = linkCount;
  const div = document.createElement('div');
  div.className = 'link-entry';
  div.id = 'link-'+n;
  div.innerHTML = `
    <div class="link-entry-header">
      <span class="link-num">#${n}</span>
      <input class="link-url-input" type="text" placeholder="https://lzt.market/..." value="${esc(url)}" id="lurl-${n}">
      <button class="remove-btn" onclick="removeLink(${n})">✕</button>
    </div>
    <input type="text" placeholder="Label (optional, shown in dashboard)" value="${esc(label)}" id="llabel-${n}" style="margin-bottom:6px;font-size:.75rem">
    <div class="link-filters">
      <div>
        <label>Min price ($)</label>
        <input type="number" placeholder="e.g. 5" value="${minP}" id="lmin-${n}">
      </div>
      <div>
        <label>Max price ($)</label>
        <input type="number" placeholder="e.g. 100" value="${maxP}" id="lmax-${n}">
      </div>
    </div>
    <div style="margin-top:6px">
      <label>Keywords (comma separated, all must match)</label>
      <input type="text" placeholder="e.g. korblox, rare" value="${esc(keywords)}" id="lkw-${n}">
    </div>
  `;
  document.getElementById('link-list').appendChild(div);
}

function removeLink(n) {
  const el = document.getElementById('link-'+n);
  if (el) el.remove();
}

function getLinkConfigs() {
  const configs = [];
  document.querySelectorAll('.link-entry').forEach(div => {
    const n = div.id.split('-')[1];
    const url = document.getElementById('lurl-'+n)?.value.trim();
    if (!url) return;
    const label = document.getElementById('llabel-'+n)?.value.trim() || '';
    const minP  = document.getElementById('lmin-'+n)?.value.trim();
    const maxP  = document.getElementById('lmax-'+n)?.value.trim();
    const kwRaw = document.getElementById('lkw-'+n)?.value.trim();
    const kws   = kwRaw ? kwRaw.split(',').map(k=>k.trim()).filter(Boolean) : [];
    configs.push({
      url,
      label,
      min_price: minP ? parseFloat(minP) : null,
      max_price: maxP ? parseFloat(maxP) : null,
      keywords:  kws,
    });
  });
  return configs;
}

// ══════════════════════════════════════════════════════════
// CHECKER CONTROL
// ══════════════════════════════════════════════════════════
async function startChecker() {
  const link_configs = getLinkConfigs();
  const webhook  = document.getElementById('webhook').value.trim();
  const interval = document.getElementById('interval').value;
  const errEl = document.getElementById('start-error');
  errEl.textContent = '';

  if (!link_configs.length) { errEl.textContent='Add at least one link.'; return; }
  if (!webhook)             { errEl.textContent='Paste a Discord webhook.'; return; }

  const res  = await fetch('/api/start',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({link_configs,webhook,interval})});
  const data = await res.json();
  if (!data.ok) { errEl.textContent='Error: '+data.error; return; }

  setRunning(true);
  startSSE();
  startStatusPoll();
  switchTab('dashboard');
}

async function stopChecker() {
  await fetch('/api/stop',{method:'POST'});
  setRunning(false);
  if (evtSource){evtSource.close();evtSource=null;}
}

async function togglePause(url) {
  const res  = await fetch('/api/pause',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
  const data = await res.json();
  return data.paused;
}

async function scanNow(url) {
  await fetch('/api/scan_now',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
  showToast('Scanning now...', url.slice(0,40), 'blue');
}

// ══════════════════════════════════════════════════════════
// SSE + STATUS POLL
// ══════════════════════════════════════════════════════════
function startSSE() {
  if (evtSource) evtSource.close();
  evtSource = new EventSource('/api/stream');
  evtSource.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.type==='ping') return;
    if (d.type==='log')    appendLog(d.ts, d.msg, d.tag);
    if (d.type==='notify') handleNotify(d);
  };
  evtSource.onerror = () => appendLog('--:--:--','Stream disconnected.','warn');
}

function startStatusPoll() {
  const poll = async () => {
    if (document.getElementById('btn-stop').disabled) return;
    try {
      const res  = await fetch('/api/status');
      const d    = await res.json();
      updateDashboard(d);
      if (d.running) setTimeout(poll, 6000);
      else setRunning(false);
    } catch { setTimeout(poll, 10000); }
  };
  setTimeout(poll, 3000);
}

// ══════════════════════════════════════════════════════════
// DASHBOARD UPDATE
// ══════════════════════════════════════════════════════════
function updateDashboard(d) {
  const stock = d.stock || {};
  const urls  = Object.keys(stock);
  const cfg   = d.config || {};
  const lcs   = cfg.link_configs || [];

  document.getElementById('stat-watching').textContent = urls.length;
  document.getElementById('stat-scans').textContent    = d.total_scans || 0;
  document.getElementById('stat-changes').textContent  = d.total_changes || 0;
  const totalStock = Object.values(stock).reduce((a,b)=>a+b,0);
  document.getElementById('stat-stock').textContent = totalStock;

  const paused = d.paused_urls || [];
  const grid   = document.getElementById('stock-grid');

  if (!urls.length) {
    grid.innerHTML = '<div class="empty">No links being watched</div>';
  } else {
    grid.innerHTML = urls.map(url => {
      const count  = stock[url];
      const lcfg   = lcs.find(c=>c.url===url)||{};
      const label  = lcfg.label || url.replace(/^https?:\/\//,'').slice(0,50);
      const isPaused = paused.includes(url);
      const prevCount = chartData[url]?.slice(-2)[0]?.count;
      let badgeCls = 'stock-badge';
      if (prevCount !== undefined && count > prevCount) badgeCls += ' up';
      else if (prevCount !== undefined && count < prevCount) badgeCls += ' down';
      const filters = [];
      if (lcfg.min_price != null) filters.push('min $'+lcfg.min_price);
      if (lcfg.max_price != null) filters.push('max $'+lcfg.max_price);
      if (lcfg.keywords?.length)  filters.push(lcfg.keywords.join(', '));
      const filterLine = filters.length ? `<div style="font-size:.68rem;color:var(--muted);margin-top:3px">${filters.join(' | ')}</div>` : '';
      return `<div class="stock-row">
        <div style="flex:1;min-width:0">
          <div class="stock-label">${esc(label)}</div>
          ${filterLine}
        </div>
        ${isPaused ? '<span class="paused-badge">PAUSED</span>' : ''}
        <span class="${badgeCls}">${count}</span>
        <div class="stock-actions">
          <button class="btn-icon" onclick="scanNow('${esc(url)}')" title="Scan now">⟳</button>
          <button class="btn-icon" onclick="togglePauseUI('${esc(url)}')" title="${isPaused?'Resume':'Pause'}">${isPaused?'▶':'⏸'}</button>
          <button class="btn-icon" onclick="viewOffers('${esc(url)}')" title="View offers">👁</button>
        </div>
      </div>`;
    }).join('');
  }

  // update chart url selector
  syncChartSel(urls);
  syncOfferSel(urls);

  // feed chart data
  if (urls.length) {
    urls.forEach(url => {
      if (!chartData[url]) chartData[url] = [];
      chartData[url].push({ts: new Date().toLocaleTimeString('en',{hour:'2-digit',minute:'2-digit'}), count: stock[url]});
      if (chartData[url].length > 30) chartData[url].shift();
    });
    redrawChart();
  }
}

async function togglePauseUI(url) {
  await togglePause(url);
  // refresh status immediately
  const res = await fetch('/api/status');
  const d   = await res.json();
  updateDashboard(d);
}

// ══════════════════════════════════════════════════════════
// CHART (canvas, no library)
// ══════════════════════════════════════════════════════════
function syncChartSel(urls) {
  const sel = document.getElementById('chart-url-sel');
  const cur = sel.value;
  sel.innerHTML = (urls||[]).map(u=>{
    const label = u.replace(/^https?:\/\//,'').slice(0,40);
    return `<option value="${esc(u)}" ${u===cur?'selected':''}>${esc(label)}</option>`;
  }).join('');
  if (!sel.value && urls?.length) sel.value = urls[0];
}

function redrawChart() {
  const sel   = document.getElementById('chart-url-sel');
  const url   = sel.value;
  const data  = chartData[url] || [];
  const empty = document.getElementById('chart-empty');
  const canvas= document.getElementById('chart');

  if (!data.length) { empty.style.display=''; canvas.style.display='none'; return; }
  empty.style.display='none'; canvas.style.display='';

  const dpr = window.devicePixelRatio||1;
  const W   = canvas.parentElement.clientWidth - 28;
  const H   = 160;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width  = W+'px';
  canvas.style.height = H+'px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr,dpr);

  const counts = data.map(p=>p.count);
  const maxC   = Math.max(...counts, 1);
  const minC   = Math.min(...counts, 0);
  const range  = maxC - minC || 1;

  const pad = {t:10,r:10,b:30,l:28};
  const pw  = W - pad.l - pad.r;
  const ph  = H - pad.t - pad.b;

  const x = i => pad.l + (i/(data.length-1||1))*pw;
  const y = v => pad.t + ph - ((v-minC)/range)*ph;

  // grid lines
  ctx.strokeStyle='#30363d'; ctx.lineWidth=0.5;
  [0,.25,.5,.75,1].forEach(f=>{
    const yy = pad.t + ph*f;
    ctx.beginPath(); ctx.moveTo(pad.l,yy); ctx.lineTo(pad.l+pw,yy); ctx.stroke();
    ctx.fillStyle='#8b949e'; ctx.font='10px JetBrains Mono,monospace';
    ctx.textAlign='right';
    ctx.fillText(Math.round(minC+(1-f)*range), pad.l-4, yy+3);
  });

  // area fill
  ctx.beginPath();
  ctx.moveTo(x(0), y(counts[0]));
  counts.forEach((c,i)=>{ if(i) ctx.lineTo(x(i),y(c)); });
  ctx.lineTo(x(counts.length-1), pad.t+ph);
  ctx.lineTo(x(0), pad.t+ph);
  ctx.closePath();
  ctx.fillStyle='rgba(88,166,255,0.12)';
  ctx.fill();

  // line
  ctx.beginPath();
  ctx.moveTo(x(0),y(counts[0]));
  counts.forEach((c,i)=>{ if(i) ctx.lineTo(x(i),y(c)); });
  ctx.strokeStyle='#58a6ff'; ctx.lineWidth=2; ctx.stroke();

  // dots
  counts.forEach((c,i)=>{
    ctx.beginPath(); ctx.arc(x(i),y(c),3,0,Math.PI*2);
    ctx.fillStyle='#58a6ff'; ctx.fill();
  });

  // x labels (first, mid, last)
  ctx.fillStyle='#8b949e'; ctx.font='9px JetBrains Mono,monospace'; ctx.textAlign='center';
  const idxs = [0, Math.floor((data.length-1)/2), data.length-1];
  idxs.forEach(i=>{ if(data[i]) ctx.fillText(data[i].ts, x(i), H-6); });
}

// ══════════════════════════════════════════════════════════
// OFFERS
// ══════════════════════════════════════════════════════════
function syncOfferSel(urls) {
  const sel = document.getElementById('offers-url-sel');
  const cur = sel.value;
  const all = urls || Object.keys(chartData);
  sel.innerHTML = all.map(u=>{
    const label = u.replace(/^https?:\/\//,'').slice(0,45);
    return `<option value="${esc(u)}" ${u===cur?'selected':''}>${esc(label)}</option>`;
  }).join('');
  if (!sel.value && all.length) sel.value = all[0];
}

async function loadOffers() {
  const url  = document.getElementById('offers-url-sel').value;
  if (!url) return;
  const res  = await fetch('/api/offers?url='+encodeURIComponent(url));
  const data = await res.json();
  renderOffers(data);
}

function renderOffers(offers) {
  const el = document.getElementById('offers-list');
  if (!offers.length) { el.innerHTML='<div class="empty">No offers found for this link</div>'; return; }
  el.innerHTML = offers.map((o,i)=>`
    <div class="offer-card">
      <button class="offer-copy" onclick="copyOffer(this,'${esc(o.replace(/'/g,"\\'"))}')">Copy</button>
      ${esc(o)}
    </div>
  `).join('');
}

function copyOffer(btn, text) {
  navigator.clipboard.writeText(text).then(()=>{
    btn.textContent='Copied!'; btn.classList.add('copied');
    setTimeout(()=>{ btn.textContent='Copy'; btn.classList.remove('copied'); },1500);
  });
}

function viewOffers(url) {
  switchTab('offers');
  setTimeout(()=>{
    const sel = document.getElementById('offers-url-sel');
    sel.value = url;
    loadOffers();
  },50);
}

// ══════════════════════════════════════════════════════════
// HISTORY
// ══════════════════════════════════════════════════════════
async function loadHistory() {
  const res  = await fetch('/api/history');
  const data = await res.json();
  const el   = document.getElementById('history-list');
  if (!data.length) { el.innerHTML='<div class="empty">No history yet</div>'; return; }
  el.innerHTML = [...data].reverse().map(row=>`
    <div class="hist-row">
      <span class="hist-ts">${row.ts}</span>
      <span class="hist-label">${esc(row.label||row.url.slice(0,35))}</span>
      <span class="hist-count">${row.count}</span>
      <span class="hist-changed">${row.changed?'CHG':''}</span>
    </div>
  `).join('');
}

// ══════════════════════════════════════════════════════════
// LOG
// ══════════════════════════════════════════════════════════
let logVisible = true;
function appendLog(ts, msg, tag) {
  const box  = document.getElementById('log-box');
  const line = document.createElement('div');
  line.className = 'log-line';
  line.innerHTML = `<span class="log-ts">${ts}</span><span class="log-${tag||'info'}">${esc(msg)}</span>`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
  document.getElementById('tab-log-wrap').style.display = '';
}
function clearLog() { document.getElementById('log-box').innerHTML=''; }
function toggleLog() {
  logVisible = !logVisible;
  document.getElementById('log-box').style.display = logVisible?'':'none';
  document.getElementById('log-toggle').textContent = logVisible?'Hide':'Show';
}

// ══════════════════════════════════════════════════════════
// TOASTS + NOTIFICATIONS
// ══════════════════════════════════════════════════════════
function showToast(title, sub, tag) {
  const colors = {ok:'var(--green)',warn:'var(--yellow)',err:'var(--red)',blue:'var(--blue)',info:'var(--muted)'};
  const wrap = document.getElementById('toast-wrap');
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = `<div class="toast-dot" style="background:${colors[tag]||colors.info}"></div>
    <div class="toast-body"><div class="toast-title">${esc(title)}</div>
    <div class="toast-sub">${esc(sub)}</div></div>
    <button class="btn-icon" onclick="this.parentElement.remove()" style="padding:3px 7px;font-size:.7rem">✕</button>`;
  wrap.appendChild(t);
  setTimeout(()=>{ t.classList.add('fade'); setTimeout(()=>t.remove(),400); }, 4000);
}

function handleNotify(d) {
  showToast(d.title, d.body, d.tag);
  if (notifGranted && document.visibilityState==='hidden') {
    new Notification('LZT Checker', { body: d.title+'\n'+d.body, icon: '' });
  }
}

async function requestNotifPerm() {
  if (!('Notification' in window)) return;
  const perm = await Notification.requestPermission();
  notifGranted = perm==='granted';
  const btn = document.getElementById('notif-btn');
  btn.textContent = notifGranted ? '🔔✓' : '🔔✗';
  showToast(notifGranted?'Notifications enabled':'Notifications blocked',
    notifGranted?'You will get alerts when stock changes':'Allow in browser settings','info');
}

// ══════════════════════════════════════════════════════════
// RUNNING STATE UI
// ══════════════════════════════════════════════════════════
function setRunning(yes) {
  document.getElementById('btn-start').disabled      = yes;
  document.getElementById('btn-stop').disabled       = !yes;
  document.getElementById('btn-start-links').disabled = yes;
  document.getElementById('btn-start-links').textContent = yes ? '● Running...' : '▶ Start Checker';
  document.getElementById('status-dot').className   = yes ? 'dot live' : 'dot';
  document.getElementById('status-label').textContent = yes ? 'RUNNING' : 'STOPPED';
}

function esc(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ══════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════
window.addEventListener('DOMContentLoaded', async () => {
  // check notification permission
  if (Notification && Notification.permission==='granted') {
    notifGranted = true;
    document.getElementById('notif-btn').textContent = '🔔✓';
  }

  // seed with one empty link
  addLink('https://lzt.market/roblox/?pmax=89&title=korblox');

  // check if already running
  try {
    const res = await fetch('/api/status');
    const d   = await res.json();
    if (d.running) {
      setRunning(true);
      updateDashboard(d);
      startSSE();
      startStatusPoll();

      // restore link config into UI
      const lcs = d.config?.link_configs || [];
      if (lcs.length) {
        document.getElementById('link-list').innerHTML='';
        linkCount=0;
        lcs.forEach(c=>addLink(c.url,c.label||'',c.min_price||'',c.max_price||'',(c.keywords||[]).join(', ')));
      }
      if (d.config?.webhook) document.getElementById('webhook').value = d.config.webhook;
      if (d.config?.interval) document.getElementById('interval').value = d.config.interval;
    }
  } catch(e) {}
});
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("\n  LZT Market Multi-Checker v2")
    print("  ─────────────────────────────")
    print("  Run 'ipconfig' in cmd, look for IPv4 under Wi-Fi")
    print("  Then open  http://<that-ip>:5000  in Safari\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

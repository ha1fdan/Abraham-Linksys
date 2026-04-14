#!/usr/bin/env python3
"""
flask_status.py — Minimal Flask server that holds the online/offline status.
wifi_connect.py POSTs to /status to flip it online.
"""

from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

_status = {"status": "offline", "ip": None}

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pi Status</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg: #0f1117;
      --card: #1a1d27;
      --border: #2a2d3a;
      --text: #e2e8f0;
      --muted: #64748b;
      --online: #22c55e;
      --offline: #ef4444;
      --accent: #6366f1;
    }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', ui-sans-serif, system-ui, sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 2.5rem 3rem;
      width: min(420px, 92vw);
      box-shadow: 0 24px 64px rgba(0,0,0,.45);
    }

    .header {
      display: flex;
      align-items: center;
      gap: .75rem;
      margin-bottom: 2rem;
    }

    .pi-icon {
      width: 36px;
      height: 36px;
      background: var(--accent);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.1rem;
      flex-shrink: 0;
    }

    .header h1 {
      font-size: 1.15rem;
      font-weight: 600;
      letter-spacing: -.01em;
    }

    .header p {
      font-size: .78rem;
      color: var(--muted);
      margin-top: .1rem;
    }

    .status-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 1.1rem 1.25rem;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      margin-bottom: .75rem;
    }

    .label {
      font-size: .8rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .06em;
      font-weight: 500;
    }

    .value {
      font-size: .95rem;
      font-weight: 600;
      font-family: ui-monospace, 'Cascadia Code', monospace;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: .45rem;
      padding: .3rem .75rem;
      border-radius: 999px;
      font-size: .85rem;
      font-weight: 600;
    }

    .badge.online  { background: rgba(34,197,94,.12);  color: var(--online);  }
    .badge.offline { background: rgba(239,68,68,.12);  color: var(--offline); }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    .badge.online  .dot { background: var(--online);  animation: pulse-green 2s infinite; }
    .badge.offline .dot { background: var(--offline); }

    @keyframes pulse-green {
      0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(34,197,94,.4); }
      50%       { opacity: .8; box-shadow: 0 0 0 5px rgba(34,197,94,0); }
    }

    .footer {
      margin-top: 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .refresh-info {
      font-size: .75rem;
      color: var(--muted);
    }

    .refresh-btn {
      background: none;
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 6px;
      padding: .3rem .65rem;
      font-size: .75rem;
      cursor: pointer;
      transition: color .15s, border-color .15s;
    }

    .refresh-btn:hover { color: var(--text); border-color: var(--muted); }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="pi-icon">&#x1F967;</div>
      <div>
        <h1>Raspberry Pi</h1>
        <p>Network status monitor</p>
      </div>
    </div>

    <div class="status-row">
      <span class="label">Status</span>
      <span id="badge" class="badge offline"><span class="dot"></span><span id="status-text">—</span></span>
    </div>

    <div class="status-row">
      <span class="label">IP Address</span>
      <span id="ip" class="value" style="color:var(--muted)">—</span>
    </div>

    <div class="footer">
      <span class="refresh-info">Auto-refresh every <span id="countdown">5</span>s</span>
      <button class="refresh-btn" onclick="poll()">Refresh</button>
    </div>
  </div>

  <script>
    let timer = 5;

    async function poll() {
      try {
        const r = await fetch('/status');
        const d = await r.json();

        const badge = document.getElementById('badge');
        const statusText = document.getElementById('status-text');
        const ip = document.getElementById('ip');

        const online = d.status === 'online';
        badge.className = 'badge ' + (online ? 'online' : 'offline');
        statusText.textContent = d.status;
        ip.textContent = d.ip || '—';
        ip.style.color = d.ip ? 'var(--text)' : 'var(--muted)';

        timer = 5;
      } catch(e) {
        console.error(e);
      }
    }

    function tick() {
      timer--;
      document.getElementById('countdown').textContent = timer;
      if (timer <= 0) { poll(); timer = 5; }
    }

    poll();
    setInterval(tick, 1000);
  </script>
</body>
</html>"""


@app.get("/")
def index():
    return render_template_string(_PAGE)


@app.get("/status")
def get_status():
    return jsonify(_status)


@app.post("/status")
def set_status():
    data = request.get_json(force=True, silent=True) or {}
    if "status" in data:
        _status["status"] = data["status"]
    if "ip" in data:
        _status["ip"] = data["ip"]
    return jsonify(_status)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)

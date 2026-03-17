from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string


# Load local .env for bare-metal runs. In Docker Compose, env_file handles this.
load_dotenv(override=False)


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


WG_IFACE = os.getenv("WG_IFACE", "wg0")
WG_CONF = os.getenv("WG_CONF") or f"/etc/wireguard/{WG_IFACE}.conf"
HANDSHAKE_FRESH_SECONDS = env_int("HANDSHAKE_FRESH_SECONDS", 180)
AUTO_REFRESH_SECONDS = env_int("AUTO_REFRESH_SECONDS", 10)
LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = env_int("LISTEN_PORT", 8000)
APP_TITLE = os.getenv("APP_TITLE", "WireGuard Status")


@dataclass
class Peer:
    name: str
    public_key: str
    allowed_ips: str
    endpoint: Optional[str]
    last_handshake: Optional[int]
    transfer_rx: Optional[int]
    transfer_tx: Optional[int]
    persistent_keepalive: Optional[int]

    @property
    def last_handshake_dt(self) -> Optional[datetime]:
        if self.last_handshake and self.last_handshake > 0:
            return datetime.fromtimestamp(self.last_handshake, tz=timezone.utc)
        return None

    @property
    def online(self) -> bool:
        if not self.last_handshake_dt:
            return False
        age = (datetime.now(timezone.utc) - self.last_handshake_dt).total_seconds()
        return age <= HANDSHAKE_FRESH_SECONDS


NAME_COMMENT_RE = re.compile(r"^#\s*(?P<name>.+?)\s*$")


def parse_names_from_config(conf_path: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    path = Path(conf_path)
    if not path.exists():
        return mapping

    pending_name: Optional[str] = None
    in_peer = False

    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue

            comment_match = NAME_COMMENT_RE.match(line)
            if comment_match:
                pending_name = comment_match.group("name")
                continue

            if line.lower() == "[peer]":
                in_peer = True
                continue

            if in_peer and line.lower().startswith("publickey"):
                value = line.split("=", 1)
                if len(value) == 2:
                    pub_key = value[1].strip()
                    mapping[pub_key] = pending_name or f"{pub_key[:8]}..."
                pending_name = None
                in_peer = False

    return mapping


def peers_from_config(conf_path: str, name_map: Dict[str, str]) -> List[Peer]:
    peers: List[Peer] = []
    path = Path(conf_path)
    if not path.exists():
        return peers

    pending_name: Optional[str] = None
    in_peer = False
    public_key: Optional[str] = None
    allowed_ips: Optional[str] = None

    def flush_current() -> None:
        nonlocal public_key, allowed_ips, in_peer, pending_name
        if public_key:
            peers.append(
                Peer(
                    name=name_map.get(public_key, pending_name or f"{public_key[:8]}..."),
                    public_key=public_key,
                    allowed_ips=allowed_ips or "",
                    endpoint=None,
                    last_handshake=None,
                    transfer_rx=None,
                    transfer_tx=None,
                    persistent_keepalive=None,
                )
            )
        public_key = None
        allowed_ips = None
        in_peer = False
        pending_name = None

    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue

            comment_match = NAME_COMMENT_RE.match(line)
            if comment_match:
                pending_name = comment_match.group("name")
                continue

            if line.startswith("["):
                if in_peer:
                    flush_current()
                in_peer = line.lower() == "[peer]"
                continue

            if not in_peer:
                continue

            if "=" not in line:
                continue

            key, value = [chunk.strip() for chunk in line.split("=", 1)]
            key = key.lower()

            if key == "publickey":
                public_key = value
            elif key == "allowedips":
                allowed_ips = value

    if in_peer:
        flush_current()

    peers.sort(key=lambda p: p.name.lower())
    return peers


def wg_dump(iface: str) -> List[List[str]]:
    result = subprocess.run(
        ["wg", "show", iface, "dump"],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = [row for row in result.stdout.splitlines() if row.strip()]
    if len(rows) <= 1:
        return []

    peers = []
    for row in rows[1:]:
        cols = row.split("\t")
        if len(cols) >= 8:
            peers.append(cols[:8])
    return peers


def get_status() -> Tuple[List[Peer], str]:
    name_map = parse_names_from_config(WG_CONF)

    try:
        rows = wg_dump(WG_IFACE)
    except (subprocess.CalledProcessError, FileNotFoundError):
        rows = []

    if not rows:
        config_peers = peers_from_config(WG_CONF, name_map)
        if config_peers:
            return config_peers, "config"
        return [], "empty"

    peers: List[Peer] = []
    for row in rows:
        (
            public_key,
            _preshared,
            endpoint,
            allowed_ips,
            latest_handshake,
            transfer_rx,
            transfer_tx,
            keepalive,
        ) = row

        try:
            last_handshake = int(latest_handshake)
        except ValueError:
            last_handshake = 0

        try:
            rx = int(transfer_rx)
        except ValueError:
            rx = 0

        try:
            tx = int(transfer_tx)
        except ValueError:
            tx = 0

        try:
            keepalive_i = int(keepalive)
        except ValueError:
            keepalive_i = None

        peers.append(
            Peer(
                name=name_map.get(public_key, f"{public_key[:8]}..."),
                public_key=public_key,
                allowed_ips=allowed_ips,
                endpoint=None if endpoint == "(none)" else endpoint,
                last_handshake=last_handshake,
                transfer_rx=rx,
                transfer_tx=tx,
                persistent_keepalive=keepalive_i,
            )
        )

    peers.sort(key=lambda peer: (not peer.online, peer.name.lower()))
    return peers, "live"


def human_bytes(value: Optional[int]) -> str:
    if value is None:
        return "-"

    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:,.0f} {unit}".replace(",", " ")
        size /= 1024
    return f"{size:.1f} PB"


def human_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "never"

    now = datetime.now(timezone.utc)
    seconds = int((now - dt).total_seconds())

    if seconds < 2:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"

    days = hours // 24
    return f"{days}d ago"


def ip_to_int(ip: str) -> int:
    try:
        parts = [int(chunk) for chunk in ip.split(".")]
        if len(parts) != 4 or any(part < 0 or part > 255 for part in parts):
            return 0
        return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]
    except Exception:
        return 0


app = Flask(__name__)


PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ app_title }} - {{ iface }}</title>
  <style>
    :root {
      color-scheme: light;
      font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    body {
      margin: 2rem;
      background: #f8fafc;
      color: #0f172a;
    }
    .topbar {
      display: flex;
      flex-wrap: wrap;
      gap: .75rem;
      align-items: baseline;
      margin-bottom: 1rem;
    }
    h1 {
      margin: 0;
      font-size: 1.25rem;
    }
    .meta {
      color: #475569;
      font-size: .9rem;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }
    .card {
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 5px 20px rgba(15, 23, 42, 0.04);
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
    th, td {
      padding: .65rem .75rem;
      border-bottom: 1px solid #e2e8f0;
      text-align: left;
      vertical-align: top;
      font-size: .92rem;
    }
    th {
      background: #f1f5f9;
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }
    tr.online {
      background: #f0fdf4;
    }
    .badge {
      display: inline-block;
      border-radius: 999px;
      padding: .18rem .5rem;
      font-size: .75rem;
      font-weight: 600;
    }
    .ok {
      background: #dcfce7;
      color: #166534;
    }
    .down {
      background: #fee2e2;
      color: #991b1b;
    }
    .empty {
      padding: 1rem;
      color: #64748b;
    }
    .tiny {
      font-size: .78rem;
      color: #64748b;
      margin-top: .2rem;
    }
  </style>
</head>
<body>
  <div class="topbar">
    <h1>{{ app_title }} <span class="mono">{{ iface }}</span></h1>
    <span class="meta">updated {{ now }}</span>
    <span class="meta">fresh <= {{ fresh }}s</span>
    <span class="meta">source: {{ source }}</span>
    <a class="meta" href="/api/status">JSON</a>
  </div>

  <div class="card">
    {% if peers %}
      <table id="peers-table">
        <thead>
          <tr>
            <th data-key="name" data-type="string">Name</th>
            <th data-key="allowedn" data-type="number">Allowed IPs</th>
            <th data-key="endpoint" data-type="string">Endpoint</th>
            <th data-key="hs" data-type="number">Last Handshake</th>
            <th data-key="rx" data-type="number">RX</th>
            <th data-key="tx" data-type="number">TX</th>
            <th data-key="online" data-type="number">Status</th>
          </tr>
        </thead>
        <tbody>
          {% for p in peers %}
            {% set first_ip = (p.allowed_ips or '').split(',')[0].split('/')[0].strip() %}
            <tr class="{% if p.online %}online{% endif %}"
                data-name="{{ p.name|lower }}"
                data-allowedn="{{ ip_to_int(first_ip) }}"
                data-endpoint="{{ p.endpoint or '' }}"
                data-hs="{{ p.last_handshake or 0 }}"
                data-rx="{{ p.transfer_rx or 0 }}"
                data-tx="{{ p.transfer_tx or 0 }}"
                data-online="{{ 1 if p.online else 0 }}">
              <td>
                <strong>{{ p.name }}</strong>
                <div class="tiny mono">{{ p.public_key[:18] }}...</div>
              </td>
              <td class="mono">{{ p.allowed_ips or '-' }}</td>
              <td class="mono">{{ p.endpoint or '-' }}</td>
              <td>{{ human_dt(p.last_handshake_dt) }}</td>
              <td>{{ human_bytes(p.transfer_rx) }}</td>
              <td>{{ human_bytes(p.transfer_tx) }}</td>
              <td>
                {% if p.online %}
                  <span class="badge ok">online</span>
                {% else %}
                  <span class="badge down">idle</span>
                {% endif %}
              </td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% else %}
      <p class="empty">No peers found. Check `WG_IFACE`, `WG_CONF`, and WireGuard access.</p>
    {% endif %}
  </div>

  <script>
    function sortRows(table, key, type, asc) {
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const factor = asc ? 1 : -1;

      rows.sort((a, b) => {
        const va = a.dataset[key] || '';
        const vb = b.dataset[key] || '';
        if (type === 'number') {
          return ((parseFloat(va) || 0) - (parseFloat(vb) || 0)) * factor;
        }
        return va.localeCompare(vb) * factor;
      });

      rows.forEach((row) => tbody.appendChild(row));
    }

    function attachSort(tableId) {
      const table = document.getElementById(tableId);
      if (!table) {
        return;
      }

      const storageKey = 'wg-sort-' + tableId;
      const readSaved = () => {
        try {
          return JSON.parse(localStorage.getItem(storageKey) || 'null');
        } catch (_err) {
          return null;
        }
      };

      const apply = (key, type, asc) => {
        sortRows(table, key, type, asc);
        try {
          localStorage.setItem(storageKey, JSON.stringify({ key, type, asc }));
        } catch (_err) {
          // No-op in private mode.
        }
      };

      table.querySelectorAll('th').forEach((th) => {
        th.addEventListener('click', () => {
          const key = th.dataset.key;
          const type = th.dataset.type || 'string';
          const current = readSaved();
          const asc = !(current && current.key === key ? current.asc : false);
          apply(key, type, asc);
        });
      });

      const saved = readSaved();
      if (saved && saved.key) {
        apply(saved.key, saved.type || 'string', !!saved.asc);
      }
    }

    document.addEventListener('DOMContentLoaded', () => {
      attachSort('peers-table');
      setTimeout(() => window.location.reload(true), {{ auto_refresh }} * 1000);
    });
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    peers, source = get_status()
    return render_template_string(
        PAGE,
        app_title=APP_TITLE,
        iface=WG_IFACE,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        fresh=HANDSHAKE_FRESH_SECONDS,
        auto_refresh=AUTO_REFRESH_SECONDS,
        peers=peers,
        human_dt=human_dt,
        human_bytes=human_bytes,
        ip_to_int=ip_to_int,
    )


@app.route("/api/status")
def api_status():
    peers, source = get_status()
    payload = [
        {
            "name": peer.name,
            "public_key": peer.public_key,
            "allowed_ips": peer.allowed_ips,
            "endpoint": peer.endpoint,
            "last_handshake": peer.last_handshake,
            "online": peer.online,
            "rx": peer.transfer_rx,
            "tx": peer.transfer_tx,
            "keepalive": peer.persistent_keepalive,
        }
        for peer in peers
    ]
    return jsonify(
        {
            "title": APP_TITLE,
            "interface": WG_IFACE,
            "config": WG_CONF,
            "fresh_seconds": HANDSHAKE_FRESH_SECONDS,
            "source": source,
            "updated_at": int(datetime.now(timezone.utc).timestamp()),
            "peers": payload,
        }
    )


@app.route("/health")
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host=LISTEN_HOST, port=LISTEN_PORT)

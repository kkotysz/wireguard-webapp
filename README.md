# wireguard-webapp

Uniwersalny panel statusu WireGuard (Flask) z API JSON, uruchamiany produkcyjnie w Dockerze przez Gunicorn + Nginx.

## Co jest konfigurowalne

Całość jest sterowana przez `.env`:

- `WG_IFACE` - nazwa interfejsu WireGuard (np. `wg0`, `wg1`)
- `WG_CONF` - ścieżka do pliku konfiguracyjnego (opcjonalna; domyślnie `/etc/wireguard/<WG_IFACE>.conf`)
- `HANDSHAKE_FRESH_SECONDS` - po ilu sekundach peer jest traktowany jako `idle`
- `AUTO_REFRESH_SECONDS` - auto-odświeżanie UI
- `NGINX_LISTEN_PORT` - port publiczny Nginx

Pełna lista: `.env.example`.

## Szybki start (Docker)

1. Skopiuj konfigurację:

```bash
cp .env.example .env
```

2. Ustaw wartości w `.env` (minimum `WG_IFACE`, opcjonalnie `WG_CONF`).

3. Uruchom stack:

```bash
docker compose up -d --build
```

4. Otwórz w przeglądarce:

```text
http://<IP_SERWERA>:<NGINX_LISTEN_PORT>
```

## Wymagania hosta

- Linux z aktywnym WireGuardem
- Docker + Docker Compose
- Dostęp do konfiguracji WireGuarda pod ścieżką z `WG_CONFIG_DIR` (domyślnie `/etc/wireguard`)

Uwaga: Compose używa `network_mode: host`, aby kontener aplikacji widział interfejsy WireGuard hosta.

## Endpointy

- `/` - panel WWW
- `/api/status` - JSON status
- `/health` - healthcheck

# WireGuard Web App

[![Docker build](https://github.com/kkotysz/wireguard-webapp/actions/workflows/docker.yml/badge.svg)](https://github.com/kkotysz/wireguard-webapp/actions/workflows/docker.yml)

A lightweight operational dashboard for **monitoring WireGuard peers on a Linux host**, exposed through a Flask web interface and JSON API and deployed with Docker, Gunicorn and Nginx.

The project is intentionally small, but it demonstrates a complete infrastructure-oriented delivery path: host networking, containerization, reverse proxying, health checks, environment-based configuration and a simple status API.

## Engineering highlights

- **Linux networking integration** — reads the state of a host WireGuard interface from inside the application container.
- **Containerized deployment** — Docker image plus Docker Compose configuration.
- **Production-style serving** — Flask behind Gunicorn and Nginx.
- **Operational visibility** — peer status, last handshake information and traffic-related state exposed in a browser-friendly dashboard.
- **JSON API** — machine-readable status endpoint for integrations or monitoring.
- **Health check** — dedicated `/health` endpoint for service supervision.
- **Environment-driven configuration** — interface name, config location, refresh interval and deployment port can be changed without editing application code.
- **Deployment helper** — repository includes a shell-based deployment workflow and Nginx template.

## Architecture

```text
browser / API client
        |
      Nginx
        |
     Gunicorn
        |
      Flask
        |
WireGuard state on Linux host
```

The application container uses host networking so it can inspect WireGuard interfaces managed by the host operating system.

## Quick start

### Requirements

- Linux host with WireGuard configured and running
- Docker
- Docker Compose

Clone the repository:

```bash
git clone https://github.com/kkotysz/wireguard-webapp.git
cd wireguard-webapp
```

Create local configuration:

```bash
cp .env.example .env
```

Adjust the values in `.env`, then start the stack:

```bash
docker compose up -d --build
```

Open:

```text
http://<SERVER_IP>:<NGINX_LISTEN_PORT>
```

## Configuration

The application is configured through environment variables. Important options include:

- `WG_IFACE` — WireGuard interface name, e.g. `wg0` or `wg1`
- `WG_CONF` — optional path to the WireGuard configuration file
- `HANDSHAKE_FRESH_SECONDS` — age threshold used to classify peer activity
- `AUTO_REFRESH_SECONDS` — browser refresh interval
- `NGINX_LISTEN_PORT` — externally exposed Nginx port

See [`.env.example`](.env.example) for the complete configuration template.

## Endpoints

- `/` — web dashboard
- `/api/status` — JSON WireGuard status
- `/health` — service health check

## Deployment notes

Docker Compose uses `network_mode: host` for the application container. This is deliberate: the service needs visibility into WireGuard interfaces on the Linux host.

The repository includes:

```text
Dockerfile
docker-compose.yml
gunicorn.conf.py
deploy/nginx/default.conf.template
deploy.sh
```

Together they provide a compact example of packaging and deploying a small infrastructure service from application code through reverse proxy configuration.

## Project scope

This repository is designed as a focused utility rather than a large platform. Its main value is practical integration of **Python application code, Linux networking and containerized operations** in a small deployable service.

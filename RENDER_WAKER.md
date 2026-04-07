# Render Waker Guide

This project now includes a production-grade waker process in render_waker.py.

## What It Does

- Sends periodic HTTP requests to keep your Render web service active.
- Defaults to 840 seconds (14 minutes), safely under the 15-minute idle sleep window.
- Uses endpoint fallback (/health, then /) if one endpoint fails.
- Retries failed requests with exponential backoff.
- Retries quickly after failed cycles to recover fast.
- Supports graceful shutdown on SIGTERM/SIGINT.
- Validates configuration and blocks unsafe intervals (>= 900 seconds).

## Render Blueprint Integration

The render.yaml file now defines two services:

- collageauto-backend (web)
- collageauto-waker (worker)

The worker starts with:

python render_waker.py

## Required Check After Deploy

Confirm that WAKER_TARGET_URL in the collageauto-waker service matches your actual backend URL.

Default currently set in render.yaml:

https://collageautomationbot.onrender.com

If your deployed backend URL differs, update WAKER_TARGET_URL in Render dashboard.

## Environment Variables

- WAKER_TARGET_URL: Base URL of service to keep alive.
- WAKER_ENDPOINTS: Comma-separated endpoints or full URLs. Default: /health,/.
- WAKER_INTERVAL_SECONDS: Heartbeat interval. Default: 840.
- WAKER_TIMEOUT_SECONDS: Request timeout per ping. Default: 20.
- WAKER_RETRIES: Retries after first failure. Default: 3.
- WAKER_RETRY_BACKOFF_SECONDS: Initial backoff. Default: 5.
- WAKER_FAILURE_RETRY_SECONDS: Delay after failed cycle. Default: 60.
- WAKER_MAX_JITTER_SECONDS: Early jitter to fire before exact interval. Default: 20.
- WAKER_EXPECTED_STATUS_MIN: Minimum accepted status. Default: 200.
- WAKER_EXPECTED_STATUS_MAX: Maximum accepted status. Default: 399.
- WAKER_VERIFY_SSL: true or false. Default: true.
- WAKER_USER_AGENT: User-Agent string.
- WAKER_LOG_LEVEL: DEBUG, INFO, WARNING, ERROR.
- WAKER_ONCE: true to run one cycle and exit.

## Local Smoke Test

Run one cycle and exit:

WAKER_TARGET_URL=https://your-backend.onrender.com /home/dheeraj/Code/actualproject/Collageautomationbot/.venv/bin/python render_waker.py --once --log-level DEBUG

Run continuously:

WAKER_TARGET_URL=https://your-backend.onrender.com /home/dheeraj/Code/actualproject/Collageautomationbot/.venv/bin/python render_waker.py

## Operational Notes

- Use HTTPS target URLs in production.
- Keep interval below 900 seconds.
- Check worker logs in Render for uptime confirmations.
- If /health is removed or changed, update WAKER_ENDPOINTS accordingly.
- The backend automation API runs one job at a time with FIFO queueing.
- Queue depth defaults to 5 waiting jobs; additional submissions return HTTP 429.

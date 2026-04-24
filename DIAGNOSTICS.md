# Diagnostics & Troubleshooting Guide

Updated: April 17, 2026 | Status: ✅ Enhanced with cold-start & crash detection

---

## 📊 What's New: Diagnostics System

Your project now includes comprehensive diagnostics to detect and report:

- ✅ **Cold starts** (service just deployed or restarted)
- ✅ **Crashes** (service crashed and is recovering)
- ✅ **Queue status** (how many automations are queued)
- ✅ **Service state** (healthy, recovering, busy, cold-starting)

---

## 🔍 Overview: Three Diagnostics Endpoints

### 1. `/health` — Basic Health Check
**Purpose**: Used by Render's health checks and uptime monitors

**Response**:
```json
{
  "status": "ok",
  "service": "lms-auto-feedback",
  "activeRun": false,
  "queuedRuns": 0,
  "maxQueueDepth": 3,
  "uptime_seconds": 45,
  "is_cold_start": true,
  "seconds_since_last_request": 3,
  "crash_count": 0,
  "restart_reason": null
}
```

**When to check**: Never - Render checks this automatically every 60 seconds

---

### 2. `/api/queue` — Queue & ETA Information
**Purpose**: Frontend uses this to show who's running and queue position

**Response**:
```json
{
  "active": {
    "requestId": "a1b2c3",
    "username": "BIT123456",
    "studentName": "John Doe",
    "position": 0,
    "etaSeconds": 75
  },
  "waiting": [
    {
      "requestId": "d4e5f6",
      "username": "BIT654321",
      "studentName": "Jane Smith",
      "position": 1,
      "etaSeconds": 165
    }
  ],
  "etaPerRunSeconds": 90
}
```

**Polling**: Frontend polls every 3 seconds (shown as "Live Queue" panel)

---

### 3. `/api/diagnostics` — Detailed Service Diagnostics (NEW)
**Purpose**: Helps diagnose why service is slow, crashed, or cold-starting

**Response**:
```json
{
  "service_state": "COLD_START",
  "reason": "Service was just deployed or restarted. Expect 20-30s latency.",
  "uptime_seconds": 15,
  "is_cold_start": true,
  "is_recovering": false,
  "crash_count": 0,
  "restart_reason": null,
  "active_run": false,
  "queued_runs": 0,
  "max_queue_depth": 3,
  "queue_full": false,
  "seconds_since_last_request": 2,
  "recommendations": [
    "Service is initializing. Wait 30-60 seconds before retrying.",
    "This is normal after a fresh deploy or Render restart."
  ]
}
```

**Service states**:
- `COLD_START`: Service booted <30s ago → expect 20-30s latency
- `RECOVERING_FROM_CRASH`: Service crashed recently → check logs
- `BUSY`: Queue is full → multiple automations queued
- `HEALTHY`: Service is ready → should work fine

**Polling**: Frontend polls every 5 seconds (1 second when running)

---

## 🎯 What You'll See on Frontend

### Healthy Service
```
✅ Service Healthy
Service is healthy and ready to accept requests.
```

### Cold-Starting Service
```
❄️ Service COLD_START
Service was just deployed or restarted. Expect 20-30s latency.
• Service is initializing. Wait 30-60 seconds before retrying.
• This is normal after a fresh deploy or Render restart.
```

### Service Recovering from Crash
```
⚠️ Service RECOVERING_FROM_CRASH
Service crashed 1 time(s) recently. Check Render logs.
• Service recently crashed. If crashes persist, check Render logs.
• Verify in Render UI that 'Always On' is enabled (prevents spin-down).
⚠️ Service has crashed 1 time(s). If this persists, check Render logs.
```

### Service Busy/Queue Full
```
⏱️ Service BUSY
Queue is full. Multiple requests are queued ahead of you.
• Queue is full. Multiple requests are queued ahead of you.
• Each automation takes ~60-120 seconds. Retry in 2-3 minutes.
```

---

## 🛠️ Troubleshooting Scenarios

### Scenario 1: "Backend may be cold-starting" Message

**What it means**: Service took >15s to respond (cold-boot)

**Diagnosis**:
1. Check `/api/diagnostics`:
   - If `is_cold_start: true` and `uptime_seconds < 30` → **Normal cold start**
   - If `crash_count > 0` → **Service crashed recently**
   - If `queue_full: true` → **Too many requests queued**

2. **Expected behavior**:
   - First request after deploy: 20-30s wait
   - Requests after service is warm: 2-5s wait

**If cold-starting happens consistently**:
   - Check Render UI → Is "Always On" enabled?
   - If not, service spins down after idle → upgrade to paid tier
   - If yes, service may be crashing repeatedly (see next scenario)

---

### Scenario 2: Request Timeout After 70 Seconds

**What it means**: Service didn't respond within timeout limit

**Diagnosis**:
1. Check `/health`:
   ```bash
   curl https://collageautomationbot.onrender.com/health
   ```

2. If request fails completely:
   - Service is **completely down** (crashed or sleeping)
   - Check Render logs for crash messages:
     - `killed ... signal 9` = Out of Memory
     - `Process exited with code 1` = Runtime error
     - No logs for >15 min = Service spinning down (not Always-On)

3. If health check succeeds but automation times out:
   - Service is alive, but **automation is very slow**
   - Check your bot optimization (not a infrastructure issue)

---

### Scenario 3: Multiple Crashes Within Minutes

**What it means**: Service keeps crashing and restarting

**Diagnosis**:
1. Check `/api/diagnostics`:
   - `crash_count > 2` and `uptime_seconds < 5min` → **Critical problem**

2. Check Render logs for error pattern:
   - **"Out of Memory"** → Container is too small (use 512MB tier)
   - **"No space left on device"** → Disk full (usually persistent)
   - **"Playwright: X11 error"** → Browser automation failed
   - **"Exception in main"** → Bot code error

3. **Solutions**:
   - Memory: Upgrade to 512MB+ tier
   - Disk: Clear `/tmp` or restart
   - Browser: Check X11 display (headless mode)
   - Code: Debug bot/feedback.py

---

## 📈 Reading the Metrics

### Uptime Seconds
- `< 30`: Service just started (cold-booting)
- `30-300`: Service warmed up, fast requests expected
- `> 300`: Service has been running >5 min, stable

### Crash Count
- `0`: No crashes (healthy)
- `1-2`: Minor issue, may be transient
- `> 2`: Systemic problem, investigate immediately

### Queue Status
- `queuedRuns: 0`: No queue, immediate execution
- `queuedRuns: 1-2`: Small queue, acceptable
- `queue_full: true`: Queue is full (request rejected with 429)

---

## 🔧 Interpreting Recommendations

Frontend displays up to 2 recommendations based on service state. Additional recommendations shown:

| Condition | Recommendation |
|-----------|-----------------|
| Cold start | "Wait 30-60 seconds before retrying" |
| Recovering from crash | "Check Render logs" + "Verify 'Always On' enabled" |
| Queue full | "Each automation takes 60-120s. Retry in 2-3 min" |
| <10 min uptime | "Server has been up <10 min. May have 5-10s latency" |
| Healthy | "✅ Service is healthy. You should be able to run now" |

---

## 🔒 Security

**No credentials exposed**: Diagnostics endpoints don't log or return any user credentials. All sensitive data is redacted.

---

## 📊 Backend Implementation Details

### Added to `server.py`:

1. **Startup tracking**:
   ```python
   _SERVICE_START_TIME: float = time.time()
   _LAST_REQUEST_TIME: float = time.time()
   _CRASH_COUNT: int = 0
   _RESTART_REASON: Optional[str] = None
   ```

2. **Enhanced `/health`** endpoint:
   - Returns `uptime_seconds`, `is_cold_start`, `crash_count`
   - Tracks `_LAST_REQUEST_TIME` on every health check

3. **New `/api/diagnostics`** endpoint:
   - Calculates `service_state` based on uptime and crash history
   - Generates context-aware recommendations
   - Returns detailed debugging info

### Added to `page.tsx`:

1. **DiagnosticsBanner component**:
   - Shows service state with color-coded warnings
   - Displays 2 most important recommendations
   - Shows crash alert if `crash_count > 0`

2. **Diagnostics polling**:
   - Polls `/api/diagnostics` every 5s (idle) or 1s (running)
   - Updates state for banner display

---

## 🧪 Testing Diagnostics Locally

```bash
# Start backend
python -m uvicorn server:app --reload --port 8000

# In another terminal, check endpoints
curl http://localhost:8000/health
curl http://localhost:8000/api/diagnostics
curl http://localhost:8000/api/queue

# Frontend should show diagnostics banner immediately
npm run dev
```

---

## 📋 Integration with Render

**Render Health Checks**:
- Render pings `/health` every 60 seconds
- If 3 consecutive checks fail → service marked unhealthy
- If unhealthy for >5 min → Render may restart service

**Our enhancement**: `/health` now returns `uptime_seconds` and `is_cold_start`, which helps diagnose whether Render restarts are working correctly.

---

## 🚀 Next Steps

### If Service is Cold-Starting Frequently:
1. Verify "Always On" is enabled in Render dashboard
2. If enabled but still cold-starting, check Render restart logs
3. If it's just first deploy, this is normal (wait 2-3 min)

### If Crashes are Happening:
1. **Immediately check Render logs**:
   - Look for "Out of Memory" → upgrade to 512MB tier
   - Look for "signal 9" → OOM, see above
   - Look for other exceptions → report to dev team

2. **Check if auto-restarts are working**:
   - Count crashes in logs
   - If >3 in 5 min, likely systemic (not transient)

### For Monitoring:
1. Set up Render alerts for unhealthy status
2. Bookmark `/api/diagnostics` for manual checks
3. Review Render logs weekly for patterns

---

## 📝 Files Modified

- `server.py`: Added startup tracking, diagnostics endpoints
- `src/app/page.tsx`: Added DiagnosticsBanner component, diagnostics polling

No breaking changes. Endpoints are backward-compatible.

---

For more help, see:
- [OPTIMIZATION.md](OPTIMIZATION.md) — Performance tuning
- [render.yaml](render.yaml) — Render configuration
- [netlify.toml](netlify.toml) — Netlify configuration

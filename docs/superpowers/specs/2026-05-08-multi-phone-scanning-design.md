# Multi-Phone Scanning Design

## Goal

Support 2-3 Android phones scanning simultaneously via ADB WiFi, with logging and clear UX.

## Constraint

Existing single-phone workflow must remain fully functional. All new code is additive.

## Architecture

### 1. PaddleOCR Concurrent Pool

- `MAX_OLLAMA_CONCURRENT: 1 → 3`
- `Semaphore(3)` + `ThreadPoolExecutor(max_workers=3)`
- Single PaddleOCR instance, thread-safe for concurrent predict()
- Each WebSocket connection processes frames independently
- Expected: ~1.3s per phone, no queuing

### 2. Multi-Device ADB Management

New functions (old ones untouched):
- `_get_all_adb_devices() → [{serial, mode, wifi_ip, model}]`
- `POST /api/adb-wifi-start-all` — batch tcpip 5555 for all USB devices
- `POST /api/adb-wifi-connect-all` — batch connect + reverse for all WiFi devices
- `GET /api/adb-devices` — list all connected devices with status
- `POST /api/open-on-phone/{serial}` — open browser on specific device

User flow:
1. Connect all phones via USB
2. Click "Enable WiFi Debug" → system runs tcpip per device
3. Unplug all USB cables
4. Click "Connect All" → system runs connect + reverse per device
5. Each phone opens localhost:8080, scans independently

### 3. Logging System

- Python `logging` module with `RotatingFileHandler`
- File: `logs/scanner.log` (5MB max, 3 backups)
- Format: `YYYY-MM-DD HH:MM:SS [LEVEL] [module] message`
- Log events: WS connect/disconnect, OCR request/result/timing, ADB operations, config changes, errors
- API: `GET /api/logs?lines=100`, `GET /api/logs/download`

### 4. Admin Panel UX

New "Device Manager" card:
- Step progress bar (1→2→3→4)
- Device list with per-device cards (name, model, status LED, action button)
- One-click batch operations
- Old single-device card remains as fallback

## Files Modified

| File | Change |
|------|--------|
| `server.py` | Logging system, OCR concurrency, multi-device ADB APIs |
| `admin.html` | Device manager UI, log viewer |
| `config.json` | Add `maxDevices`, `logLevel` settings |

## Verification

1. Single phone works exactly as before
2. Two phones scan simultaneously, each ~1.3s response
3. Logs capture all events, accessible via API
4. Admin panel shows all devices with clear status

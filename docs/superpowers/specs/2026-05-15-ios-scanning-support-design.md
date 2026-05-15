# iOS Scanning Support (Mac + iPhone USB)

**Date:** 2026-05-15
**Author:** Claude
**Status:** Draft — pending review

## Background

Contract Scanner AI currently supports Android phones via ADB (USB reverse + WiFi debugging) and generic browsers via LAN IP. However, iOS Safari blocks `getUserMedia` on non-secure contexts (`http://LAN_IP:8080`), making wireless scanning impossible for iPhone/iPad users.

The only viable path for iOS is **Mac USB Internet Sharing**: connect iPhone to Mac via USB, enable Internet Sharing on Mac, then access `http://localhost:8080` from iPhone Safari (localhost is a secure context).

## Goal

Add iOS scanning guidance to the project without breaking existing Android/macOS flows. Minimal code, maximum clarity.

## Approach

**Method B: Panel Guidance (lightweight frontend + startup hint)**

- Detect iPhone USB connection at startup and print a hint
- Add an iOS guidance card to the admin panel
- Update README with step-by-step instructions

## Detailed Design

### 1. Backend — `run.sh` Startup Hint

Insert after the existing startup banner (line ~48):

```bash
# Detect iPhone/iPad via USB for iOS scanning guidance
if command -v system_profiler &>/dev/null && \
   system_profiler SPUSBDataType 2>/dev/null | grep -qiE "iPhone|iPad"; then
    echo "🍎 iPhone/iPad detected via USB."
    echo "   iOS Scan: System Settings → General → Sharing → Internet Sharing (USB)"
    echo "   Then open Safari on iPhone: http://localhost:${PORT}"
fi
```

**Error handling:**
- `system_profiler` missing → silently skip (fallback for very old Macs)
- No iPhone connected → no extra output
- Non-blocking: does not affect service startup

### 2. Frontend — `admin.html` iOS Card

Add a collapsible "iOS (Safari)" card below the existing connection mode area.

**Collapsed state:**
- Title: "iOS 扫描 (Safari)" with a chevron icon
- One-line hint: "iPhone 通过 USB 连接 Mac 后扫描"

**Expanded state:**
1. Mac: 系统设置 → 通用 → 共享 → 互联网共享 (USB)
2. iPhone: USB 线连接 Mac
3. iPhone Safari: 访问 `http://localhost:8080`
4. 允许摄像头权限

**Interactive elements:**
- "复制链接" button → copies `http://localhost:8080` to clipboard
- Uses existing design system colors and border radius

**Constraints:**
- Does not interfere with Android ADB workflow
- Does not auto-open or steal focus

### 3. Documentation — `README.md`

Add iOS section under "手机端打开扫描器":

```markdown
- **iOS (iPhone/iPad)**:
  1. Mac 系统设置 → 通用 → 共享 → 开启"互联网共享"（共享来源: Wi-Fi，用以下端口: USB）
  2. iPhone 用 USB 线连接 Mac
  3. iPhone 打开 Safari，访问 `http://localhost:8080`
  4. 允许摄像头权限后即可扫描
```

## Out of Scope

- Windows + iPhone support (requires HTTPS self-signed certs, much larger scope)
- Auto-configuring Mac Internet Sharing via AppleScript (requires admin privileges, fragile across macOS versions)
- Native iOS app wrapper

## Testing Checklist

- [ ] `run.sh` prints iPhone hint when iPhone is connected via USB
- [ ] `run.sh` stays silent when no iPhone is connected
- [ ] admin.html iOS card expands/collapses correctly
- [ ] "复制链接" button copies correct URL
- [ ] Android ADB "开启无线连接" flow remains intact
- [ ] README iOS instructions are clear for non-technical users

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `system_profiler` not available on old Macs | Fallback: silently skip detection |
| User forgets to enable Internet Sharing | Documented in README + admin panel card |
| iOS card clutters admin UI for Android-only users | Card is collapsed by default |

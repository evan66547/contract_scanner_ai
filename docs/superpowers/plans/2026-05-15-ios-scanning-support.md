# iOS Scanning Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add iPhone/iPad scanning support guidance using Tailscale HTTPS as the recommended path, plus same-Wi-Fi Mac IP fallback. Do not instruct iPhone users to open Mac services through `localhost`.

**Architecture:** Zero-breaking-change addition. Run-time USB detection in `run.sh`, collapsible guidance card in `admin.html`, documentation in `README.md`.

**Tech Stack:** Bash, HTML/CSS/JS, Markdown

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `run.sh` | Modify | Detect iPhone USB at startup, print iOS hint |
| `admin.html` | Modify | Add collapsible iOS (Safari) guidance card |
| `README.md` | Modify | Add iOS step-by-step instructions |

---

### Task 1: run.sh — iPhone USB Detection

**Files:**
- Modify: `run.sh:48-50`

- [ ] **Step 1: Add iPhone detection block after startup banner**

Insert after line 48 (after the ADB reverse hint):

```bash
# Detect iPhone/iPad via USB for iOS scanning guidance
if command -v system_profiler &>/dev/null && \
   system_profiler SPUSBDataType 2>/dev/null | grep -qiE "iPhone|iPad"; then
    echo "🍎 iPhone/iPad detected via USB."
    echo "   iOS Safari cannot use Mac localhost/ADB reverse."
    echo "   Recommended: tailscale serve --bg http://localhost:${PORT}"
    echo "   Same Wi-Fi fallback: http://<Mac-LAN-IP>:${PORT}"
fi
```

- [ ] **Step 2: Verify syntax**

Run: `bash -n run.sh`
Expected: No output (syntax OK)

- [ ] **Step 3: Test detection logic**

Run: `system_profiler SPUSBDataType 2>/dev/null | grep -qiE "iPhone|iPad" && echo "DETECTED" || echo "NOT_DETECTED"`
Expected: "NOT_DETECTED" (unless iPhone is plugged in)

- [ ] **Step 4: Commit**

```bash
git add run.sh
git commit -m "feat(ios): detect iPhone USB at startup and print hint"
```

---

### Task 2: admin.html — iOS Guidance Card

**Files:**
- Modify: `admin.html` (near existing connection mode area)

- [ ] **Step 1: Locate insertion point**

Find the closing `</div>` of the ADB hint section (`id="adb-hint"`). Insert the iOS card after it.

- [ ] **Step 2: Add iOS card HTML**

```html
<!-- iOS Scanning Card -->
<div style="margin-top:16px;border:1px solid rgba(99,102,241,0.15);border-radius:10px;overflow:hidden">
  <div onclick="toggleIosCard()" style="display:flex;align-items:center;justify-content:space-between;padding:12px 14px;background:linear-gradient(135deg,#eef2ff,#f5f3ff);cursor:pointer">
    <div style="display:flex;align-items:center;gap:8px;font-weight:600;color:#4f46e5;font-size:13px">
      <span>🍎</span> iOS 扫描 (Safari)
    </div>
    <span id="ios-chevron" style="color:#6366f1;transition:transform 0.2s">▶</span>
  </div>
  <div id="ios-content" style="display:none;padding:14px;font-size:12px;color:var(--text-main);line-height:1.8">
    <ol style="margin:0 0 12px 18px;padding:0">
      <li>推荐：Mac 运行 <code style="background:rgba(0,0,0,0.06);padding:2px 6px;border-radius:4px">tailscale serve --bg http://localhost:8080</code></li>
      <li>iPhone: 打开 Safari，访问 <code style="background:rgba(0,0,0,0.06);padding:2px 6px;border-radius:4px">https://&lt;machine&gt;.&lt;tailnet&gt;.ts.net</code></li>
      <li>同 Wi-Fi 可尝试访问 <code style="background:rgba(0,0,0,0.06);padding:2px 6px;border-radius:4px">http://&lt;Mac-LAN-IP&gt;:8080</code></li>
      <li>不要在 iPhone 上输入 <code style="background:rgba(0,0,0,0.06);padding:2px 6px;border-radius:4px">localhost:8080</code>，它指向 iPhone 自己</li>
    </ol>
    <button onclick="copyIosTailscaleCommand()" style="padding:6px 12px;border-radius:6px;border:none;background:#4f46e5;color:#fff;font-size:12px;cursor:pointer">📋 复制 Tailscale 命令</button>
    <span id="ios-copy-feedback" style="margin-left:8px;font-size:11px;color:#10b981;opacity:0;transition:opacity 0.3s">已复制!</span>
  </div>
</div>
```

- [ ] **Step 3: Add toggle and copy JavaScript**

In the existing `<script>` block, add:

```javascript
function toggleIosCard() {
  const content = document.getElementById('ios-content');
  const chevron = document.getElementById('ios-chevron');
  const isOpen = content.style.display === 'block';
  content.style.display = isOpen ? 'none' : 'block';
  chevron.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(90deg)';
}

function copyIosTailscaleCommand() {
  const port = window.location.port || '8080';
  const command = `tailscale serve --bg http://localhost:${port}`;
  navigator.clipboard.writeText(command).then(() => {
    const feedback = document.getElementById('ios-copy-feedback');
    feedback.style.opacity = '1';
    setTimeout(() => feedback.style.opacity = '0', 1500);
  });
}
```

- [ ] **Step 4: Verify no syntax errors**

Open `admin.html` in browser, check DevTools console for JS errors.

- [ ] **Step 5: Commit**

```bash
git add admin.html
git commit -m "feat(ios): add collapsible iOS scanning guidance card"
```

---

### Task 3: README.md — iOS Instructions

**Files:**
- Modify: `README.md` (mobile scanner section, both EN and CN)

- [ ] **Step 1: Add iOS section to English README**

After the existing "Wired (USB) Connection" bullet, add:

```markdown
- **iOS (iPhone/iPad) via Tailscale HTTPS (recommended)**:
  1. Install Tailscale on both Mac and iPhone, log in with the same account
  2. Run on Mac: `tailscale serve --bg http://localhost:8080`
  3. Open Safari on iPhone and visit `https://<machine>.<tailnet>.ts.net`
  4. Allow camera permission when prompted
- **iOS on the same Wi-Fi (fallback)**:
  1. Find the Mac LAN IP, for example `192.168.1.x`
  2. Open Safari on iPhone and visit `http://<Mac-LAN-IP>:8080`
  3. Do not use `http://localhost:8080` on iPhone; it points to the iPhone itself
```

- [ ] **Step 2: Add iOS section to Chinese README**

After the existing "有线连接 (ADB)" bullet, add:

```markdown
- **iOS (iPhone/iPad) 通过 Tailscale HTTPS (推荐)**: 
  1. Mac 与 iPhone 安装 Tailscale 并登录同一账号
  2. Mac 终端运行：`tailscale serve --bg http://localhost:8080`
  3. iPhone Safari 访问 `https://<设备名>.<tailnet>.ts.net`
  4. 允许摄像头权限后即可扫描
- **iOS 同 Wi-Fi 访问 (备用)**:
  1. 查看 Mac 局域网 IP，例如 `192.168.1.x`
  2. iPhone Safari 访问 `http://<Mac-LAN-IP>:8080`
  3. 不要在 iPhone 上访问 `http://localhost:8080`，它指向 iPhone 自己
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(ios): add iOS USB scanning instructions to README"
```

---

### Task 4: Verification

- [ ] **Step 1: run.sh detection**
  - Run `./run.sh` without iPhone connected → verify no 🍎 hint appears
  - (Optional) Run with iPhone connected → verify 🍎 hint appears

- [ ] **Step 2: admin.html card**
  - Open `http://localhost:8080/admin.html`
  - Click "iOS 扫描 (Safari)" header → card expands
  - Click again → card collapses
  - Click "复制 Tailscale 命令" → clipboard contains `tailscale serve --bg http://localhost:8080`
  - Verify Android ADB "开启无线连接" button still works

- [ ] **Step 3: README review**
  - Preview README.md rendered view
  - Verify iOS instructions appear in both EN and CN sections
  - Verify no broken markdown formatting

- [ ] **Step 4: Final commit / push**

```bash
git log --oneline -4  # verify 3 clean commits
git push origin main  # if authorized
```

---

## Self-Review

**1. Spec coverage:**
- ✅ run.sh startup hint → Task 1
- ✅ admin.html iOS card → Task 2
- ✅ README documentation → Task 3
- ✅ Testing/verification → Task 4

**2. Placeholder scan:**
- ✅ No TBD/TODO/fill-in-details
- ✅ All code blocks contain actual code
- ✅ All commands have expected output

**3. Type consistency:**
- ✅ `localhost:${PORT}` used consistently across run.sh and admin.html JS
- ✅ Button IDs and function names consistent within admin.html

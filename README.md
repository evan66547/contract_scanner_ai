# Contract Scanner AI

**Local privacy-first OCR scanner: phone camera matches contract and document targets in real time.**

[![python](https://img.shields.io/badge/python-3.10~3.12-yellow.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![license](https://img.shields.io/badge/license-Personal_Use-important.svg)](./LICENSE)

[English](#english) · [中文](#chinese) · [Full guide](./docs/DETAILED_README.md)

Built for debt-recovery / evidence hunting: scan piles of paper with a phone, match company names or contract IDs against a local target list.

## Features

- **Local / privacy-first** — MLX GLM-OCR, Ollama, PaddleOCR; optional Baidu / OCR.Space
- **Phone as camera** — WebSocket frame stream to a Mac/PC server
- **Fuzzy match in browser** — Levenshtein + haptic feedback on hit
- **Admin panel** — Excel/CSV targets, engine switch, live config (`admin.html`)
- **Android ADB / iOS Tailscale** — wired or HTTPS tunnel options

## Quick start

```bash
git clone https://github.com/evan66547/contract_scanner_ai.git
cd contract_scanner_ai
bash run.sh          # Mac/Linux  · Windows: deploy.bat / run.bat
make live-check      # optional smoke
```

- Admin: `http://localhost:8093/admin.html`
- Scanner: same Wi‑Fi URL printed by `run.sh`, or ADB / Tailscale (see [full guide](./docs/DETAILED_README.md))

## Docs

- [Detailed README (EN + 中文)](./docs/DETAILED_README.md) — engines, Tailscale, ADB, admin
- Config: `config.example.json` · Targets: `targets.example.json`

## Privacy

No hardcoded API keys or private lists in this repo. Configure cloud OCR only in the admin panel if needed.

---

<span id="english"></span>
### English one-liner

Phone browser → WebSocket → local OCR → fuzzy match against `targets.json`. See [docs/DETAILED_README.md](./docs/DETAILED_README.md).

<span id="chinese"></span>
### 中文一句话

手机摄像头采集画面 → WebSocket 到本机 → OCR → 与目标清单模糊匹配。完整说明见 [docs/DETAILED_README.md](./docs/DETAILED_README.md)。

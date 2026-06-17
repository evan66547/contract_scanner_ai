#!/usr/bin/env python3
"""Live OCR checks for local GLM-OCR, PaddleOCR, and LAN IP detection.

This is intentionally separate from smoke_regression.py because it depends on
local runtime services/models being available.
"""

import asyncio
import base64
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed = 0
failed = 0


def _result(name: str, ok: bool, detail: str = ""):
    global passed, failed
    tag = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    msg = f"  [{tag}] {name}"
    if detail:
        msg += f" - {detail}"
    print(msg)


def _test_image_b64() -> str:
    from PIL import Image, ImageDraw

    buf = io.BytesIO()
    img = Image.new("RGB", (320, 120), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), "Test OCR 123", fill="black")
    img.save(buf, format="JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode()


async def check_glm_ocr(image_b64: str):
    print("\n=== GLM OCR local provider ===")

    import aiohttp
    from ocr import OcrRuntime

    async with aiohttp.ClientSession() as session:
        rt = OcrRuntime(os.path.join(ROOT, "config.json"), session)
        ocr_cfg = rt.get_config().get("ocr", {})
        provider = ocr_cfg.get("provider", "mlx")
        if provider == "ollama":
            cfg = ocr_cfg.get("ollama", {})
            model = cfg.get("model", "glm-ocr")
            base_url = cfg.get("baseUrl", "http://localhost:11434").rstrip("/")

            try:
                async with session.get(f"{base_url}/api/tags", timeout=3) as resp:
                    _result("Ollama tags reachable", resp.status == 200, f"status={resp.status}")
            except Exception as e:
                _result("Ollama tags reachable", False, str(e))
                await rt.close()
                return

            started = time.time()
            text = await rt.recognize_ollama(image_b64, cfg)
        else:
            cfg = ocr_cfg.get("mlx", {})
            model = cfg.get("model", "mlx-community/GLM-OCR-8bit")

            started = time.time()
            text = await rt.recognize_mlx(image_b64, cfg)
        elapsed_ms = int((time.time() - started) * 1000)
        normalized = "".join(text.split())
        _result(
            f"{model} recognizes test image",
            "TestOCR123" in normalized,
            f"{elapsed_ms}ms text={text[:80]!r}",
        )
        await rt.close()


async def check_paddle_ocr(image_b64: str):
    print("\n=== PaddleOCR ===")

    import aiohttp
    from ocr import OcrRuntime

    async with aiohttp.ClientSession() as session:
        rt = OcrRuntime(os.path.join(ROOT, "config.json"), session)
        started = time.time()
        text = await rt.recognize_paddle(image_b64)
        elapsed_ms = int((time.time() - started) * 1000)
        normalized = "".join(text.split())
        _result(
            "PaddleOCR recognizes test image",
            "TestOCR123" in normalized,
            f"{elapsed_ms}ms text={text[:80]!r}",
        )
        await rt.close()


def check_lan_ip():
    print("\n=== LAN IP Detection ===")

    from server import SERVER_PORT, _get_local_ips

    ips = _get_local_ips()
    best = ips[0][0] if ips else ""
    ok = bool(best)
    _result(
        "LAN scanner URL available",
        ok,
        f"http://{best}:{SERVER_PORT}" if ok else "no private LAN IP detected",
    )


async def main():
    print("live_ocr_check.py - contract_scanner_ai")
    image_b64 = _test_image_b64()
    await check_glm_ocr(image_b64)
    await check_paddle_ocr(image_b64)
    check_lan_ip()

    total = passed + failed
    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

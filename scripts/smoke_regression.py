#!/usr/bin/env python3
"""Smoke regression for scan_stats cache, OcrRuntime lifecycle, and Paddle fallback.

Run:
  python3 scripts/smoke_regression.py
  .venv/bin/python3 scripts/smoke_regression.py
"""

import asyncio
import json
import os
import sys
import tempfile
import time

# Ensure project root on sys.path
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
        msg += f" — {detail}"
    print(msg)


# ───────────────────────────────────────
# 1) scan_stats cache consistency
# ───────────────────────────────────────

def test_scan_stats():
    """Replicate server.py _load/_save logic and verify mtime cache behavior."""
    print("\n=== 1) scan_stats cache consistency ===")

    import json as _json

    tmpdir = tempfile.mkdtemp()
    stats_file = os.path.join(tmpdir, "scan_stats.json")
    cache = None
    mtime = 0.0

    def load():
        nonlocal cache, mtime
        try:
            cm = os.stat(stats_file).st_mtime
        except OSError:
            cm = 0.0
        if cache is not None and cm == mtime:
            _result("load cache hit", True)
            return cache
        try:
            with open(stats_file) as f:
                data = _json.load(f)
            cache = data
            mtime = cm
            _result("load from disk", True)
            return data
        except Exception:
            _result("load from disk", False, "unexpected exception")
            return {}

    def save(stats):
        nonlocal cache, mtime
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tmp", delete=False, dir=tmpdir
        ) as f:
            _json.dump(stats, f)
        os.replace(f.name, stats_file)
        cache = stats
        try:
            mtime = os.stat(stats_file).st_mtime
        except OSError:
            mtime = 0.0

    # 1a: write-then-read immediate consistency
    save({"2026-05-25": 2310, "2026-05-26": 638})
    d = load()
    _result(
        "write-then-read matches",
        d == {"2026-05-25": 2310, "2026-05-26": 638},
        f"got {d}" if d != {"2026-05-25": 2310, "2026-05-26": 638} else "",
    )

    # 1b: second load hits cache (no disk IO)
    d2 = load()
    _result("second load cache hit", d2 is d, "different object")

    # 1c: external file modification triggers reload
    time.sleep(0.1)
    with open(stats_file, "w") as f:
        _json.dump({"2026-05-25": 2311, "2026-05-26": 0}, f)
    d3 = load()
    _result(
        "external mod reloads",
        d3 == {"2026-05-25": 2311, "2026-05-26": 0},
        f"got {d3}" if d3.get("2026-05-25") != 2311 else "",
    )

    # cleanup
    os.unlink(stats_file)
    os.rmdir(tmpdir)


# ───────────────────────────────────────
# 2) OcrRuntime post-close behavior
# ───────────────────────────────────────

async def test_ocr_runtime_lifecycle():
    print("\n=== 2) OcrRuntime post-close behavior ===")

    from ocr import OcrRuntime
    import aiohttp

    session = aiohttp.ClientSession()
    rt = OcrRuntime(os.path.join(ROOT, "config.json"), session)

    # 2a: close sets _closed
    await rt.close()
    _result("close sets _closed", rt._closed is True)

    # 2b: recognize methods return error string, not exception
    for name, coro_fn in [
        ("recognize_ollama", lambda: rt.recognize_ollama("abc", {})),
        ("recognize_baidu", lambda: rt.recognize_baidu("abc", {})),
        ("recognize_paddle", lambda: rt.recognize_paddle("abc")),
    ]:
        try:
            result = await coro_fn()
            is_err = isinstance(result, str) and "已关闭" in result
            _result(f"{name} returns error str", is_err, f"got: {result[:60]}")
        except Exception as e:
            _result(f"{name} returns error str", False, f"threw {type(e).__name__}: {e}")

    # 2c: get_baidu_token returns "" (falsy, not error string)
    token = await rt.get_baidu_token("key", "secret")
    _result(
        "get_baidu_token returns empty str",
        token == "",
        f"got: repr={repr(token)}",
    )

    # 2d: double close is safe
    try:
        await rt.close()
        _result("double close safe", True)
    except Exception as e:
        _result("double close safe", False, str(e))

    await session.close()


# ───────────────────────────────────────
# 3) Paddle fallback (ocr() → ocr.predict())
# ───────────────────────────────────────

async def test_paddle_fallback():
    print("\n=== 3) Paddle fallback ===")

    from ocr import OcrRuntime
    import aiohttp

    session = aiohttp.ClientSession()
    rt = OcrRuntime(os.path.join(ROOT, "config.json"), session)

    # Mock: predict() raises, ocr() returns text
    class FakePaddle:
        def predict(self, img):
            raise RuntimeError("Engine 'paddle_static' is unavailable")

        def ocr(self, img, cls=False):
            return [[[None, ["fallback text", 0.99]]]]

    rt._paddle_ocr_instance = FakePaddle()

    # Use PIL to generate a valid JPEG that OpenCV can decode
    import base64
    try:
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (1, 1), (255, 255, 255)).save(buf, format="JPEG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        # Fallback: skip this test if PIL unavailable
        _result("paddle ocr() fallback works", False, "PIL not available")
        _result("recognize_paddle public works", False, "PIL not available")
        await rt.close()
        await session.close()
        return

    result = await rt._paddle(img_b64)
    has_fallback = "fallback text" in result
    _result(
        "paddle ocr() fallback works",
        has_fallback,
        f"got: {result[:80]}" if not has_fallback else "",
    )

    # Also test that recognize_paddle (public) works
    result2 = await rt.recognize_paddle(img_b64)
    has_fallback2 = "fallback text" in result2
    _result(
        "recognize_paddle public works",
        has_fallback2,
        f"got: {result2[:80]}" if not has_fallback2 else "",
    )

    await rt.close()
    await session.close()


# ───────────────────────────────────────

def main():
    print("smoke_regression.py — contract_scanner_ai")

    # Sync tests
    test_scan_stats()

    # Async tests
    asyncio.run(test_ocr_runtime_lifecycle())
    asyncio.run(test_paddle_fallback())

    # Summary
    total = passed + failed
    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failed > 0:
        print("FAILED")
        sys.exit(1)
    else:
        print("ALL PASSED")


if __name__ == "__main__":
    main()

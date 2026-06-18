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
import types

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

    def coerce_count(value):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def adjust(day, delta):
        stats = load()
        stats[day] = max(0, coerce_count(stats.get(day, 0)) + delta)
        save(stats)
        return stats[day]

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

    # 1d: manual adjustment clamps at zero
    down = adjust("2026-05-26", -1)
    _result("adjust decrement clamps at zero", down == 0, f"got {down}")

    # 1e: invalid stored counts are treated as zero before increment
    save({"2026-05-27": "bad"})
    up = adjust("2026-05-27", 1)
    _result("adjust increment coerces invalid count", up == 1, f"got {up}")

    # cleanup
    os.unlink(stats_file)
    os.rmdir(tmpdir)


def test_scan_stats_v2_device_helpers():
    print("\n=== 2) scan_stats v2 device helpers ===")

    import server

    stats = {
        "schema": "v2",
        "global": {"2026-06-12": 3},
        "devices": {
            "phone-a": {"2026-06-12": 2},
            "phone-b": {"2026-06-12": 1},
        },
        "deviceMeta": {
            "phone-a": {"label": "Pixel 8", "lastSeen": "2026-06-12"},
            "phone-b": {"label": "iPhone", "lastSeen": "2026-06-12"},
        },
    }

    _result(
        "global count uses v2 global",
        server._get_global_scan_count(stats, "2026-06-12") == 3,
        f"got {server._get_global_scan_count(stats, '2026-06-12')}",
    )

    rows = server._device_scan_rows(stats, "2026-06-12")
    _result(
        "device rows sorted by count",
        rows[0]["label"] == "Pixel 8" and rows[0]["count"] == 2 and rows[1]["label"] == "iPhone",
        f"got {rows}",
    )

    server._set_global_scan_count(stats, "2026-06-12", 4)
    server._set_device_scan_count(stats, "phone-b", "2026-06-12", 2, "iPhone")
    _result(
        "set global mirrors legacy date",
        stats["global"]["2026-06-12"] == 4 and stats["2026-06-12"] == 4,
        f"got global={stats.get('global')} legacy={stats.get('2026-06-12')}",
    )
    _result(
        "set device count updates meta",
        stats["devices"]["phone-b"]["2026-06-12"] == 2 and stats["deviceMeta"]["phone-b"]["label"] == "iPhone",
        f"got {stats['devices'].get('phone-b')} {stats['deviceMeta'].get('phone-b')}",
    )

    legacy_rows = server._device_scan_rows(
        {"schema": "v2", "global": {"2026-06-12": 5}, "devices": {}, "deviceMeta": {}},
        "2026-06-12",
    )
    _result(
        "unassigned row covers legacy device-less scans",
        legacy_rows == [{"device_id": "unassigned", "label": "未归属设备", "count": 5, "lastSeen": "2026-06-12"}],
        f"got {legacy_rows}",
    )


# ───────────────────────────────────────
# 2) OcrRuntime post-close behavior
# ───────────────────────────────────────

async def test_ocr_runtime_lifecycle():
    print("\n=== 2) OcrRuntime post-close behavior ===")

    from ocr import OcrRuntime
    import aiohttp

    session = aiohttp.ClientSession()
    rt = OcrRuntime(os.path.join(ROOT, "config.json"), session)
    rt._mlx_model = object()
    rt._mlx_processor = object()
    rt._mlx_config = object()
    rt._mlx_model_name = "test-model"

    # 2a: close sets _closed
    await rt.close()
    _result("close sets _closed", rt._closed is True)
    _result(
        "close releases cached mlx refs",
        rt._mlx_model is None and rt._mlx_processor is None and rt._mlx_config is None and rt._mlx_model_name is None,
    )

    # 2b: recognize methods return error string, not exception
    for name, coro_fn in [
        ("recognize_ollama", lambda: rt.recognize_ollama("abc", {})),
        ("recognize_baidu", lambda: rt.recognize_baidu("abc", {})),
        ("recognize_paddle", lambda: rt.recognize_paddle("abc")),
        ("recognize_mlx", lambda: rt.recognize_mlx("abc", {})),
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


async def test_server_runtime_resource_close():
    print("\n=== 2b) Server runtime resource close ===")

    import server

    class FakeRuntime:
        def __init__(self):
            self.closed = 0

        async def close(self):
            self.closed += 1

    class FakeSession:
        closed = False

        async def close(self):
            self.closed = True

    old = (server.http_session, server._ocr_runtime, server._fallback_ocr_runtime)
    session = FakeSession()
    primary = FakeRuntime()
    fallback = FakeRuntime()
    try:
        server.http_session = session
        server._ocr_runtime = primary
        server._fallback_ocr_runtime = fallback
        await server._close_runtime_resources()
        _result("closes primary runtime", primary.closed == 1)
        _result("closes fallback runtime", fallback.closed == 1)
        _result("closes http session", session.closed is True)
        _result("clears runtime globals", server._ocr_runtime is None and server._fallback_ocr_runtime is None)
    finally:
        server.http_session, server._ocr_runtime, server._fallback_ocr_runtime = old


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

    fake_np = types.SimpleNamespace(uint8="uint8", frombuffer=lambda data, dtype: data)
    fake_cv2 = types.SimpleNamespace(IMREAD_COLOR=1, imdecode=lambda data, flags: object())
    old_np = sys.modules.get("numpy")
    old_cv2 = sys.modules.get("cv2")
    sys.modules["numpy"] = fake_np
    sys.modules["cv2"] = fake_cv2

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
        if old_np is None:
            sys.modules.pop("numpy", None)
        else:
            sys.modules["numpy"] = old_np
        if old_cv2 is None:
            sys.modules.pop("cv2", None)
        else:
            sys.modules["cv2"] = old_cv2
        return

    try:
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
    finally:
        await rt.close()
        await session.close()
        if old_np is None:
            sys.modules.pop("numpy", None)
        else:
            sys.modules["numpy"] = old_np
        if old_cv2 is None:
            sys.modules.pop("cv2", None)
        else:
            sys.modules["cv2"] = old_cv2


# ───────────────────────────────────────
# 4) PaddleOCR v6 tiny initialization
# ───────────────────────────────────────

async def test_paddle_v6_tiny_init():
    print("\n=== 4) PaddleOCR v6 tiny init ===")

    from ocr import OcrRuntime
    import aiohttp

    tmpdir = tempfile.mkdtemp()
    cfg_path = os.path.join(tmpdir, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({
            "ocr": {
                "provider": "paddle",
                "ollama": {
                    "baseUrl": "http://localhost:11434",
                    "model": "glm-ocr",
                    "keepAlive": "10m",
                },
                "baidu": {"apiKey": "", "secretKey": ""},
                "ocrspace": {"apiKey": "", "language": "chs"},
                "openai": {
                    "apiKey": "",
                    "model": "gpt-4o-mini",
                    "baseUrl": "https://api.openai.com/v1",
                },
                "paddle": {"useGpu": False},
            }
        }, f)

    calls = []

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    fake_paddle = types.SimpleNamespace(set_flags=lambda flags: None)
    fake_paddleocr = types.ModuleType("paddleocr")
    fake_paddleocr.PaddleOCR = FakePaddleOCR

    old_paddle = sys.modules.get("paddle")
    old_paddleocr = sys.modules.get("paddleocr")
    sys.modules["paddle"] = fake_paddle
    sys.modules["paddleocr"] = fake_paddleocr

    session = aiohttp.ClientSession()
    rt = OcrRuntime(cfg_path, session)
    try:
        rt._get_paddle_ocr()
        kwargs = calls[0] if calls else {}
        _result(
            "uses PP-OCRv6",
            kwargs.get("ocr_version") == "PP-OCRv6",
            f"got: {kwargs.get('ocr_version')}",
        )
        _result(
            "uses tiny detection model",
            kwargs.get("text_detection_model_name") == "PP-OCRv6_tiny_det",
            f"got: {kwargs.get('text_detection_model_name')}",
        )
        _result(
            "uses tiny recognition model",
            kwargs.get("text_recognition_model_name") == "PP-OCRv6_tiny_rec",
            f"got: {kwargs.get('text_recognition_model_name')}",
        )
        _result(
            "keeps CPU default",
            kwargs.get("device") == "cpu",
            f"got: {kwargs.get('device')}",
        )
    finally:
        await rt.close()
        await session.close()
        if old_paddle is None:
            sys.modules.pop("paddle", None)
        else:
            sys.modules["paddle"] = old_paddle
        if old_paddleocr is None:
            sys.modules.pop("paddleocr", None)
        else:
            sys.modules["paddleocr"] = old_paddleocr
        os.unlink(cfg_path)
        os.rmdir(tmpdir)


# ───────────────────────────────────────
# 5) Ollama OCR response cleanup
# ───────────────────────────────────────

def test_ollama_cleanup():
    print("\n=== 5) Ollama OCR cleanup ===")

    from ocr import clean_ollama_ocr_text

    raw = "Test OCR 123\n\n```markdown\nTest OCR 123\n```\n---\n```\n"
    cleaned = clean_ollama_ocr_text(raw)
    _result(
        "removes markdown loop noise",
        cleaned == "Test OCR 123",
        f"got: {cleaned!r}",
    )

    prompt_leak = (
        "拖拽 Excel/CSV 到此处，或点击选择文件\n"
        "你是一个高精度的合同 OCR 助手。请提取图片中的所有文字。如果是复印件，请忽略背景噪点、模糊的印章和阴影。"
    )
    cleaned_leak = clean_ollama_ocr_text(prompt_leak)
    _result(
        "removes leaked OCR prompt",
        cleaned_leak == "拖拽 Excel/CSV 到此处，或点击选择文件",
        f"got: {cleaned_leak!r}",
    )

    short_prompt_leak = "全国统一服务电话111\nwww.ems.com.cn\n高精度的合同 OCR 助手\n图片中没有文字内容"
    cleaned_short = clean_ollama_ocr_text(short_prompt_leak)
    _result(
        "removes short prompt fragments",
        cleaned_short == "全国统一服务电话111\nwww.ems.com.cn",
        f"got: {cleaned_short!r}",
    )


# ───────────────────────────────────────
# 6) MLX provider config and dispatch compatibility
# ───────────────────────────────────────

async def test_mlx_provider_config_and_dispatch():
    print("\n=== 6) MLX provider config and dispatch compatibility ===")

    from ocr import OcrRuntime
    import aiohttp

    tmpdir = tempfile.mkdtemp()
    cfg_path = os.path.join(tmpdir, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({
            "ocr": {
                "provider": "mlx",
                "ollama": {
                    "baseUrl": "http://localhost:11434",
                    "model": "glm-ocr",
                    "keepAlive": "10m",
                },
                "baidu": {"apiKey": "", "secretKey": ""},
                "ocrspace": {"apiKey": "", "language": "chs"},
                "openai": {
                    "apiKey": "",
                    "model": "gpt-4o-mini",
                    "baseUrl": "https://api.openai.com/v1",
                },
                "paddle": {"useGpu": False},
            }
        }, f)

    session = aiohttp.ClientSession()
    rt = OcrRuntime(cfg_path, session)
    try:
        cfg = rt.get_config()
        mlx_cfg = cfg.get("ocr", {}).get("mlx", {})
        _result(
            "adds mlx default model",
            mlx_cfg.get("model") == "mlx-community/GLM-OCR-8bit",
            f"got: {mlx_cfg}",
        )
        _result(
            "keeps ollama compatibility block",
            cfg.get("ocr", {}).get("ollama", {}).get("model") == "glm-ocr",
            f"got: {cfg.get('ocr', {}).get('ollama')}",
        )
        _result(
            "adds scan defaults for admin",
            cfg.get("scan", {}).get("interval") == 1500
            and cfg.get("scan", {}).get("width") == 640
            and cfg.get("roi", {}).get("width") == 90
            and cfg.get("matching", {}).get("minMatchRatio") == 0.6
            and cfg.get("ui", {}).get("showOverlay") is True,
            f"got: scan={cfg.get('scan')} roi={cfg.get('roi')} matching={cfg.get('matching')} ui={cfg.get('ui')}",
        )

        async def fake_mlx(image_b64, runtime_cfg):
            return f"mlx:{runtime_cfg.get('model')}:{image_b64}"

        async def fake_ollama(image_b64, runtime_cfg):
            return f"ollama:{runtime_cfg.get('model')}:{image_b64}"

        rt._mlx = fake_mlx
        rt._ollama = fake_ollama
        text = await rt.recognize_text("img")
        _result(
            "dispatches mlx provider",
            text == "mlx:mlx-community/GLM-OCR-8bit:img",
            f"got: {text}",
        )

        cfg["ocr"]["provider"] = "ollama"
        rt._config_cache = cfg
        text = await rt.recognize_text("img")
        _result(
            "ollama provider still dispatches",
            text == "ollama:glm-ocr:img",
            f"got: {text}",
        )
    finally:
        await rt.close()
        await session.close()
        os.unlink(cfg_path)
        os.rmdir(tmpdir)


# ───────────────────────────────────────

def main():
    print("smoke_regression.py — contract_scanner_ai")

    # Sync tests
    test_scan_stats()
    test_scan_stats_v2_device_helpers()

    # Async tests
    asyncio.run(test_ocr_runtime_lifecycle())
    asyncio.run(test_server_runtime_resource_close())
    asyncio.run(test_paddle_fallback())
    asyncio.run(test_paddle_v6_tiny_init())
    test_ollama_cleanup()
    asyncio.run(test_mlx_provider_config_and_dispatch())

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

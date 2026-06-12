"""OCR Runtime — 多引擎 OCR 运行时（Phase 1: 配置管理 + 基础类定义）

本模块逐步接管 server.py 中的 OCR 相关逻辑：
  Phase 1: OcrRuntime + get_config() (mtime 缓存) + TokenBucketRateLimiter + OcrResult
  后续阶段: dispatch_ocr / call_* 迁移至此
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

_OLLAMA_PROMPT_LEAK_MARKERS = (
    "你是一个高精度的合同 OCR 助手",
    "你是一个高精度的合同OCR助手",
    "高精度的合同 OCR 助手",
    "高精度的合同OCR助手",
    "请提取图片中的所有文字",
    "图片中没有文字内容",
    "如果是复印件，请忽略背景噪点",
    "请确保公司名称、日期等关键信息准确",
    "直接输出识别到的文字内容",
    "不要包含任何解释、说明或 Markdown 格式",
)


def clean_ollama_ocr_text(text: str) -> str:
    """Remove common GLM-OCR formatting loops while preserving OCR text lines."""
    cleaned = []
    previous = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("```"):
            continue
        if re.fullmatch(r"[-*_`=\s]{3,}", line):
            continue
        leak_positions = [line.find(marker) for marker in _OLLAMA_PROMPT_LEAK_MARKERS if marker in line]
        if leak_positions:
            line = line[:min(leak_positions)].strip()
            if not line:
                continue
        if line == previous:
            continue
        cleaned.append(line)
        previous = line
    return "\n".join(cleaned).strip()


# ═══════════════════════════════════════════════
# Token Bucket 限流器
# ═══════════════════════════════════════════════

class TokenBucketRateLimiter:
    """异步令牌桶限流，用于控制 OCR API 调用频率"""

    def __init__(self, rate: float, per: float):
        self.rate = rate
        self.per = per
        self.allowance = rate
        self.last_check = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            while True:
                current = time.time()
                time_passed = current - self.last_check
                self.last_check = current
                self.allowance += time_passed * (self.rate / self.per)
                if self.allowance > self.rate:
                    self.allowance = self.rate
                if self.allowance >= 1.0:
                    self.allowance -= 1.0
                    return
                await asyncio.sleep((1.0 - self.allowance) * (self.per / self.rate))


# ═══════════════════════════════════════════════
# OCR 结果数据类
# ═══════════════════════════════════════════════

@dataclass
class OcrResult:
    """统一 OCR 识别结果"""
    text: str
    provider: str = ""
    confidence: float = 0.0
    latency_ms: float = 0.0
    error: Optional[str] = None


# ═══════════════════════════════════════════════
# OCR Runtime
# ═══════════════════════════════════════════════

class OcrRuntime:
    """OCR 运行时：持有配置、HTTP session、提供配置读取（mtime 缓存）"""

    def __init__(self, config_path: str, http_session: aiohttp.ClientSession):
        self.config_path = config_path
        self.http_session = http_session
        self._config_cache: Optional[dict] = None
        self._config_mtime: float = 0.0
        self._baidu_token_cache = {"token": None, "expires": 0}
        self._baidu_limiter = TokenBucketRateLimiter(rate=2.0, per=1.0)
        self._paddle_ocr_instance = None
        # Keep single worker to match existing server.py behavior.
        self._ocr_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ocr"
        )
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ocr_executor is not None:
            self._ocr_executor.shutdown(wait=False)
            self._ocr_executor = None
        self._paddle_ocr_instance = None
        self.http_session = None

    def get_config(self) -> dict:
        """读取 OCR 配置，mtime 变化时重新加载，自动迁移旧格式。

        等价于原 server.py 的 get_ocr_config()，增加 mtime 缓存避免重复磁盘 IO。
        """
        path = Path(self.config_path)
        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            current_mtime = 0.0

        if self._config_cache is not None and current_mtime == self._config_mtime:
            return self._config_cache

        cfg = self._load_json(self.config_path, {})
        cfg = self._migrate_config(cfg)
        cfg = self._ensure_forward_compat(cfg)

        self._config_cache = cfg
        self._config_mtime = current_mtime
        return cfg

    # ── 内部工具 ──

    @staticmethod
    def _load_json(filepath: str, default_val: Any = None) -> Any:
        if default_val is None:
            default_val = {}
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return default_val

    @staticmethod
    def _save_json(filepath: str, data: dict):
        import tempfile
        dir_name = os.path.dirname(filepath) or "."
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".tmp", delete=False, dir=dir_name
        ) as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(f.name, filepath)

    def _migrate_config(self, cfg: dict) -> dict:
        """迁移旧格式配置（顶层 ollamaModel → ollama.provider 结构）"""
        if "ocr" not in cfg:
            old_model = cfg.pop("ollamaModel", "glm-ocr")
            cfg["ocr"] = {
                "provider": "ollama",
                "ollama": {
                    "baseUrl": "http://localhost:11434",
                    "model": old_model,
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
            self._save_json(self.config_path, cfg)
        return cfg

    @staticmethod
    def _ensure_forward_compat(cfg: dict) -> dict:
        """确保新 provider 配置块存在（向前兼容）"""
        if "ocrspace" not in cfg.get("ocr", {}):
            cfg["ocr"]["ocrspace"] = {"apiKey": "", "language": "chs"}
        if "paddle" not in cfg.get("ocr", {}):
            cfg["ocr"]["paddle"] = {"useGpu": False}
        paddle_cfg = cfg["ocr"]["paddle"]
        paddle_cfg.setdefault("useGpu", False)
        paddle_cfg.setdefault("ocrVersion", "PP-OCRv6")
        paddle_cfg.setdefault("textDetectionModelName", "PP-OCRv6_tiny_det")
        paddle_cfg.setdefault("textRecognitionModelName", "PP-OCRv6_tiny_rec")
        return cfg

    # ── Provider adapters（Phase 3） ──

    async def _ocrspace(self, image_b64: str, ocrspace_cfg: dict) -> str:
        """OCR.space provider — 从 server.call_ocrspace() 1:1 迁移"""
        api_key = ocrspace_cfg.get("apiKey", "")
        if not api_key:
            return "[OCR.space Error: API Key 未配置]"
        lang = ocrspace_cfg.get("language", "chs")

        url = "https://api.ocr.space/parse/image"
        payload = aiohttp.FormData()
        payload.add_field("base64Image", f"data:image/jpeg;base64,{image_b64}")
        payload.add_field("language", lang)
        payload.add_field("isOverlayRequired", "false")

        headers = {"apikey": api_key}

        try:
            async with self.http_session.post(url, data=payload, headers=headers) as resp:
                data = await resp.json()
                if data.get("OCRExitCode") != 1:
                    return f"[OCR.space Error: {data.get('ErrorMessage', 'unknown')}]"
                results = data.get("ParsedResults", [])
                if not results:
                    return ""
                return results[0].get("ParsedText", "").replace("\r\n", "").replace("\n", "")
        except Exception as e:
            return f"[OCR.space Error: {str(e)}]"

    async def _get_baidu_token(self, api_key: str, secret_key: str) -> str:
        cache = self._baidu_token_cache
        if cache["token"] and time.time() < cache["expires"]:
            return cache["token"]
        url = (
            "https://aip.baidubce.com/oauth/2.0/token?"
            f"grant_type=client_credentials&client_id={api_key}&client_secret={secret_key}"
        )
        async with self.http_session.post(url) as resp:
            data = await resp.json()
            token = data.get("access_token", "")
            cache["token"] = token
            cache["expires"] = time.time() + data.get("expires_in", 2592000) - 60
            return token

    async def _baidu(self, image_b64: str, baidu_cfg: dict) -> str:
        """Baidu provider（从 server.call_baidu 1:1 迁移）"""
        await self._baidu_limiter.acquire()

        api_key = baidu_cfg.get("apiKey", "")
        secret_key = baidu_cfg.get("secretKey", "")
        if not api_key or not secret_key:
            return "[Baidu Error: API Key 未配置]"

        baidu_apis = [
            ("accurate_basic", "通用文字识别（高精度版）"),
            ("general_basic", "通用文字识别（标准版）"),
            ("webimage", "网络图片文字识别"),
            ("webimage_loc", "网络图片文字识别（含位置版）"),
            ("handwriting", "手写文字识别"),
            ("numbers", "数字识别"),
        ]
        try:
            token = await self._get_baidu_token(api_key, secret_key)
            errors = []
            for api_name, api_label in baidu_apis:
                url = (
                    "https://aip.baidubce.com/rest/2.0/ocr/v1/"
                    f"{api_name}?access_token={token}"
                )
                params = {
                    "image": image_b64,
                    "language_type": "CHN_ENG",
                    "detect_direction": "true",
                }
                async with self.http_session.post(url, data=params) as resp:
                    data = await resp.json()
                    text = ""
                    if "words_result" in data:
                        for w in data["words_result"]:
                            text += w.get("words", "")
                    elif "forms_result" in data:
                        for form in data["forms_result"]:
                            for body in form.get("body", []):
                                text += body.get("words", "")
                    if text.strip():
                        return text
                    error_code = data.get("error_code", 0)
                    if error_code == 17:
                        errors.append(f"{api_label}: 额度用尽")
                        continue
                    if error_code == 18:
                        errors.append(f"{api_label}: QPS超限")
                        continue
                    err_code = data.get("error_code", "unknown")
                    return f"[Baidu Error: {data.get('error_msg', f'code {err_code}')}]"
            return f"[Baidu Error: 所有接口额度用尽 - {'; '.join(errors)}]"
        except Exception as e:
            return f"[Baidu Error: {str(e)}]"

    def _get_paddle_ocr(self):
        """PaddleOCR 初始化（从 server._get_paddle_ocr 迁移）"""
        if self._paddle_ocr_instance is None:
            try:
                import paddle
                paddle.set_flags({'FLAGS_use_mkldnn': True})
            except Exception:
                pass

            from paddleocr import PaddleOCR
            paddle_cfg = self.get_config().get("ocr", {}).get("paddle", {})
            self._paddle_ocr_instance = PaddleOCR(
                lang='ch',
                ocr_version=paddle_cfg.get("ocrVersion", "PP-OCRv6"),
                text_detection_model_name=paddle_cfg.get(
                    "textDetectionModelName", "PP-OCRv6_tiny_det"
                ),
                text_recognition_model_name=paddle_cfg.get(
                    "textRecognitionModelName", "PP-OCRv6_tiny_rec"
                ),
                text_det_limit_side_len=480,
                text_recognition_batch_size=1,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device="gpu:0" if paddle_cfg.get("useGpu") else "cpu"
            )
        return self._paddle_ocr_instance

    async def _paddle(self, image_b64: str) -> str:
        """PaddleOCR provider（从 server.call_paddle 1:1 迁移）"""
        try:
            import numpy as np
            import cv2
        except ImportError as e:
            return f"[PaddleOCR Error: 缺少依赖 {e.name}]"

        try:
            import base64
            ocr = self._get_paddle_ocr()
            img_bytes = base64.b64decode(image_b64)
            nparray = np.frombuffer(img_bytes, np.uint8)
            img_array = cv2.imdecode(nparray, cv2.IMREAD_COLOR)

            if img_array is None:
                return "[PaddleOCR Error: 图像解码失败]"

            loop = asyncio.get_running_loop()
            def _run_ocr():
                # PaddleOCR 版本差异兼容：
                # - 新版常见 predict(...)
                # - 旧版常见 ocr(...)
                if hasattr(ocr, "predict"):
                    try:
                        return ocr.predict(img_array)
                    except Exception:
                        # 部分环境（如 paddle_static engine 不可用）predict 会失败，
                        # 回退到旧版 ocr() 路径继续识别。
                        if hasattr(ocr, "ocr"):
                            return ocr.ocr(img_array, cls=False)
                        raise
                if hasattr(ocr, "ocr"):
                    return ocr.ocr(img_array, cls=False)
                raise AttributeError("PaddleOCR instance has neither predict nor ocr")

            result = await loop.run_in_executor(self._ocr_executor, _run_ocr)

            texts = []
            def _append_legacy_line(line):
                if (
                    isinstance(line, list)
                    and len(line) >= 2
                    and isinstance(line[1], (list, tuple))
                    and len(line[1]) >= 1
                ):
                    text = line[1][0]
                    if isinstance(text, str):
                        texts.append(text)

            if result:
                for item in result:
                    if "rec_texts" in item:
                        texts.extend(item["rec_texts"])
                        continue
                    # ocr(...) 老格式：[[[box], (text, score)], ...]
                    if isinstance(item, list):
                        # 结构 A: [box, [text, score]]
                        _append_legacy_line(item)
                        # 结构 B: [[box, [text, score]], ...]
                        for line in item:
                            _append_legacy_line(line)
            return "".join(texts)
        except Exception as e:
            return f"[PaddleOCR Error: {str(e)}]"

    async def _ollama(self, image_b64: str, ollama_cfg: dict) -> str:
        """Ollama provider（从 server.call_ollama 迁移）"""
        base_url = ollama_cfg.get("baseUrl", "http://localhost:11434")
        model = ollama_cfg.get("model", "glm-ocr")
        keep_alive = ollama_cfg.get("keepAlive", "10m")
        num_predict = int(ollama_cfg.get("numPredict", 160))
        timeout_seconds = int(ollama_cfg.get("timeoutSeconds", 60))

        url = f"{base_url.rstrip('/')}/api/generate"
        payload = {
            "model": model,
            "prompt": "你是一个高精度的合同 OCR 助手。请提取图片中的所有文字。如果是复印件，请忽略背景噪点、模糊的印章和阴影。请确保公司名称、日期等关键信息准确。直接输出识别到的文字内容，不要包含任何解释、说明或 Markdown 格式：",
            "images": [image_b64],
            "stream": False,
            "keep_alive": keep_alive,
            "options": {
                "num_predict": num_predict,
                "temperature": 0,
            },
        }

        # 使用独立 session，避免 Ollama 死连接污染全局连接池
        ocr_timeout = aiohttp.ClientTimeout(total=timeout_seconds, sock_read=timeout_seconds, connect=10)
        async with aiohttp.ClientSession(timeout=ocr_timeout) as session:
            try:
                async with session.get(
                    f"{base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=2)
                ) as check:
                    if check.status != 200:
                        return "[Ollama Error: Ollama 未响应]"
            except Exception:
                return "[Ollama Error: Ollama 离线，请检查是否启动]"

            max_retries = 1
            for attempt in range(max_retries + 1):
                try:
                    async with session.post(url, json=payload, timeout=ocr_timeout) as resp:
                        if resp.status != 200:
                            return f"[Ollama Error: {resp.status}]"
                        data = await resp.json()
                        return clean_ollama_ocr_text(data.get("response", ""))

                except asyncio.TimeoutError:
                    if attempt < max_retries:
                        logger.info(f"[Ollama] 第 {attempt + 1} 次请求超时，3 秒后重试...")
                        await asyncio.sleep(3)
                        continue
                    return "[Timeout: Ollama 响应超时，请检查模型是否卡死]"
                except Exception as e:
                    return f"[Ollama Error: {str(e)}]"

    # ── 公开接口 ──

    def _check_alive(self) -> Optional[str]:
        if self._closed:
            return "[Error: OCR Runtime 已关闭]"

    async def get_baidu_token(self, api_key: str, secret_key: str) -> str:
        if self._closed: return ""
        return await self._get_baidu_token(api_key, secret_key)

    async def recognize_ollama(self, image_b64: str, ollama_cfg: dict) -> str:
        if (e := self._check_alive()): return e
        return await self._ollama(image_b64, ollama_cfg)

    async def recognize_baidu(self, image_b64: str, baidu_cfg: dict) -> str:
        if (e := self._check_alive()): return e
        return await self._baidu(image_b64, baidu_cfg)

    async def recognize_paddle(self, image_b64: str) -> str:
        if (e := self._check_alive()): return e
        return await self._paddle(image_b64)

    # ── OCR 调度（Phase 2） ──

    async def recognize_text(self, image_b64: str) -> str:
        """调度 OCR provider，等价于 server.dispatch_ocr()。"""
        if (e := self._check_alive()): return e
        from server import call_openai

        cfg = self.get_config()
        provider = cfg["ocr"].get("provider", "ollama")
        if provider == "baidu":
            return await self._baidu(image_b64, cfg["ocr"]["baidu"])
        elif provider == "ocrspace":
            return await self._ocrspace(image_b64, cfg["ocr"].get("ocrspace", {}))
        elif provider == "openai":
            return await call_openai(image_b64, cfg["ocr"]["openai"])
        elif provider == "paddle":
            return await self._paddle(image_b64)
        else:
            return await self._ollama(image_b64, cfg["ocr"].get("ollama", {}))

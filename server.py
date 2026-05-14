import os
import json
import base64
import asyncio
import hashlib
import hmac
import time
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, List, Optional, Set
from io import BytesIO, StringIO
import csv
import socket
import subprocess

import multiprocessing
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import openpyxl
import aiohttp
import logging
from logging.handlers import RotatingFileHandler
import concurrent.futures

# === 服务配置 ===
SERVER_PORT = int(os.environ.get('PORT', os.environ.get('SERVER_PORT', 8080)))
DEBUG_WS = os.environ.get("DEBUG_WS", "0") == "1"

# === 全局 aiohttp Session（复用连接池，避免每次请求创建新连接） ===
http_session: Optional[aiohttp.ClientSession] = None

async def _reset_http_session():
    """重置 aiohttp session，清理可能卡死的连接池"""
    global http_session
    if http_session and not http_session.closed:
        await http_session.close()
    timeout = aiohttp.ClientTimeout(total=60, connect=10)
    http_session = aiohttp.ClientSession(timeout=timeout)
    logger.info("🔄 aiohttp Session 已重置（清理死连接）")

# === WebSocket 并发控制 ===
MAX_WS_CONNECTIONS = 5  # Support up to 5 devices
MAX_OCR_CONCURRENT = 5  # 增加并发限制
ws_semaphore: Optional[asyncio.Semaphore] = None
active_ws_clients: Set[WebSocket] = set()

# ================================
# PaddleOCR 引擎（针对 M1 Pro 深度优化）
# ================================
_paddle_ocr_instance = None
# 建议单并发，让单个任务占满 CPU 核心以降低单帧延迟，防止系统卡顿
ocr_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用生命周期：启动时创建 HTTP Session，预热模型，关闭时释放资源"""
    global http_session, ws_semaphore
    timeout = aiohttp.ClientTimeout(total=60, connect=10)
    http_session = aiohttp.ClientSession(timeout=timeout)
    ws_semaphore = asyncio.Semaphore(MAX_OCR_CONCURRENT)
    logger.info("✅ aiohttp Session 已创建")
    logger.info(f"✅ OCR 并发限制: {MAX_OCR_CONCURRENT}")

    # 预热 GLM-OCR 模型（加载到显存/内存）
    asyncio.create_task(warmup_model())

    yield
    await http_session.close()
    logger.info("🔚 aiohttp Session 已关闭")

async def warmup_model():
    """启动后异步预热模型（仅 Ollama 引擎，不抢占其他模型显存）"""
    try:
        cfg = get_ocr_config()
        if cfg["ocr"].get("provider", "ollama") != "ollama":
            logger.info("⏭️ 当前非 Ollama 引擎，跳过预热")
            return
        ollama_cfg = cfg["ocr"].get("ollama", {})
        base_url = ollama_cfg.get("baseUrl", "http://localhost:11434")
        model = ollama_cfg.get("model", "glm-ocr")

        # 检查当前是否已有其他模型占用显存
        async with http_session.get(f"{base_url}/api/ps", timeout=aiohttp.ClientTimeout(total=5)) as ps_resp:
            if ps_resp.status == 200:
                ps_data = await ps_resp.json()
                loaded = [m.get("name", "") for m in ps_data.get("models", [])]
                other_loaded = [n for n in loaded if model not in n]
                if other_loaded:
                    logger.info(f"⏭️ 检测到其他模型运行中 ({', '.join(other_loaded)})，跳过预热避免抢占显存")
                    return
                if any(model in n for n in loaded):
                    logger.info(f"✅ {model} 已在内存中，无需预热")
                    return

        logger.info(f"⏳ 正在预热模型 {model}...")
        url = f"{base_url.rstrip('/')}/api/generate"
        payload = {"model": model, "prompt": "hi", "stream": False, "keep_alive": ollama_cfg.get("keepAlive", "10m")}
        async with http_session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status == 200:
                logger.info(f"✅ 模型 {model} 预热完成，已加载到内存")
            else:
                logger.warning(f"⚠️ 模型预热失败: HTTP {resp.status}")
    except Exception as e:
        logger.warning(f"⚠️ 模型预热异常: {e}")

app = FastAPI(title="Contract Scanner AI", lifespan=lifespan)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# === 日志系统 ===
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "scanner.log")

logger = logging.getLogger("scanner")
logger.setLevel(logging.INFO)
# Prevent duplicate handlers on reload
if not logger.handlers:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(module)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    # Also log to console
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(console)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
TARGETS_FILE = os.path.join(BASE_DIR, "targets.json")

NAME_ALIASES = {'识别对象', '公司名称', '公司名', '名称', '公司', '目标', '对象', 'company', 'name', 'target', '企业名称', '单位名称', '客户名称'}
INFO_ALIASES = {'显示信息', '附加信息', '备注', '日期', '开单日期', '合同编号', 'info', 'note', 'date', '说明'}

# ADB 无线调试：缓存手机 WiFi IP（开启 tcpip 时记录，拔线后仍可用）
adb_wifi_ip_cache: Optional[str] = None
INFO2_ALIASES = {'合同总额', '欠款金额', '金额', '总额', 'amount', 'total', 'balance', 'debt', '合同金额', '订单金额'}

# Pydantic models
class ExcelUploadResult(BaseModel):
    headers: List[str]
    preview: List[dict]
    totalRows: int
    nameCol: int
    infoCol: int
    infoCol2: int
    allRows: List[List[Any]]

class ImportConfirmReq(BaseModel):
    nameCol: int
    infoCol: int
    infoCol2: int
    headers: List[str] = []
    allRows: List[List[Any]]

class AdbWifiConnectReq(BaseModel):
    wifi_ip: Optional[str] = None

def load_json(filepath, default_val):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")
    return default_val

def save_json(filepath, data):
    import tempfile
    dir_name = os.path.dirname(filepath) or '.'
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.tmp', delete=False, dir=dir_name) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(f.name, filepath)

def get_ocr_config():
    """获取 OCR 配置，自动迁移旧格式"""
    cfg = load_json(CONFIG_FILE, {})
    if "ocr" not in cfg:
        # 迁移旧格式
        old_model = cfg.pop("ollamaModel", "glm-ocr")
        cfg["ocr"] = {
            "provider": "ollama",
            "ollama": {"baseUrl": "http://localhost:11434", "model": old_model, "keepAlive": "10m"},
            "baidu": {"apiKey": "", "secretKey": ""},
            "ocrspace": {"apiKey": "", "language": "chs"},
            "openai": {"apiKey": "", "model": "gpt-4o-mini", "baseUrl": "https://api.openai.com/v1"},
            "paddle": {"useGpu": False}
        }
        save_json(CONFIG_FILE, cfg)
    # 确保 ocrspace 配置块存在（向前兼容）
    if "ocrspace" not in cfg.get("ocr", {}):
        cfg["ocr"]["ocrspace"] = {"apiKey": "", "language": "chs"}
    # 确保 paddle 配置块存在（向前兼容）
    if "paddle" not in cfg.get("ocr", {}):
        cfg["ocr"]["paddle"] = {"useGpu": False}
    return cfg

# === 百度 OCR access_token 缓存 ===
_baidu_token_cache = {"token": None, "expires": 0}

async def get_baidu_token(api_key: str, secret_key: str) -> str:
    if _baidu_token_cache["token"] and time.time() < _baidu_token_cache["expires"]:
        return _baidu_token_cache["token"]
    url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={api_key}&client_secret={secret_key}"
    async with http_session.post(url) as resp:
        data = await resp.json()
        token = data.get("access_token", "")
        _baidu_token_cache["token"] = token
        _baidu_token_cache["expires"] = time.time() + data.get("expires_in", 2592000) - 60
        return token

# ================================
# OCR 引擎调度器
# ================================
async def dispatch_ocr(base64_img: str) -> str:
    cfg = get_ocr_config()
    provider = cfg["ocr"].get("provider", "ollama")
    if provider == "baidu":
        return await call_baidu(base64_img, cfg["ocr"]["baidu"])
    elif provider == "ocrspace":
        return await call_ocrspace(base64_img, cfg["ocr"].get("ocrspace", {}))
    elif provider == "openai":
        return await call_openai(base64_img, cfg["ocr"]["openai"])
    elif provider == "paddle":
        return await call_paddle(base64_img)
    else:
        return await call_ollama(base64_img, cfg["ocr"].get("ollama", {}))

async def call_ollama(base64_img: str, ollama_cfg: dict = None) -> str:
    if ollama_cfg is None:
        cfg = get_ocr_config()
        ollama_cfg = cfg["ocr"].get("ollama", {})
    base_url = ollama_cfg.get("baseUrl", "http://localhost:11434")
    model = ollama_cfg.get("model", "glm-ocr")
    keep_alive = ollama_cfg.get("keepAlive", "10m")

    url = f"{base_url.rstrip('/')}/api/generate"
    # 针对合同复印件优化 Prompt：增加对干扰项的过滤指令，并强调实体提取
    payload = {
        "model": model,
        "prompt": "你是一个高精度的合同 OCR 助手。请提取图片中的所有文字。如果是复印件，请忽略背景噪点、模糊的印章和阴影。请确保公司名称、日期等关键信息准确。直接输出识别到的文字内容，不要包含任何解释、说明或 Markdown 格式：",
        "images": [base64_img],
        "stream": True,
        "keep_alive": keep_alive
    }

    # 使用独立 session，避免 Ollama 死连接污染全局连接池
    ocr_timeout = aiohttp.ClientTimeout(total=120, sock_read=30, connect=10)
    async with aiohttp.ClientSession(timeout=ocr_timeout) as session:
        try:
            async with session.get(f"{base_url}/api/tags", timeout=aiohttp.ClientTimeout(total=2)) as check:
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

                    parts = []
                    async for line in resp.content:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        parts.append(chunk.get("response", ""))
                        if chunk.get("done"):
                            break
                    return "".join(parts)

            except asyncio.TimeoutError:
                if attempt < max_retries:
                    logger.info(f"[Ollama] 第 {attempt + 1} 次请求超时，3 秒后重试...")
                    await asyncio.sleep(3)
                    continue
                return "[Timeout: Ollama 响应超时，请检查模型是否卡死]"
            except Exception as e:
                return f"[Ollama Error: {str(e)}]"

_BAIDU_OCR_APIS = [
    ("accurate_basic", "通用文字识别（高精度版）"),
    ("general_basic", "通用文字识别（标准版）"),
    ("webimage", "网络图片文字识别"),
    ("webimage_loc", "网络图片文字识别（含位置版）"),
    ("handwriting", "手写文字识别"),
    ("numbers", "数字识别"),
]

async def call_baidu(base64_img: str, baidu_cfg: dict) -> str:
    api_key = baidu_cfg.get("apiKey", "")
    secret_key = baidu_cfg.get("secretKey", "")
    if not api_key or not secret_key:
        return "[Baidu Error: API Key 未配置]"

    try:
        token = await get_baidu_token(api_key, secret_key)
        errors = []
        for api_name, api_label in _BAIDU_OCR_APIS:
            url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/{api_name}?access_token={token}"
            params = {"image": base64_img, "language_type": "CHN_ENG", "detect_direction": "true"}
            async with http_session.post(url, data=params) as resp:
                data = await resp.json()
                # Extract text from various Baidu OCR response formats
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
                if error_code == 17:  # Open api daily request limit reached
                    errors.append(f"{api_label}: 额度用尽")
                    continue
                if error_code == 18:  # QPS limit
                    errors.append(f"{api_label}: QPS超限")
                    continue
                return f"[Baidu Error: {data.get('error_msg', f'code {data.get('error_code', 'unknown')}')}]"
        return f"[Baidu Error: 所有接口额度用尽 - {'; '.join(errors)}]"
    except Exception as e:
        return f"[Baidu Error: {str(e)}]"

async def call_ocrspace(base64_img: str, ocrspace_cfg: dict) -> str:
    api_key = ocrspace_cfg.get("apiKey", "")
    if not api_key:
        return "[OCR.space Error: API Key 未配置]"
    lang = ocrspace_cfg.get("language", "chs")

    url = "https://api.ocr.space/parse/image"
    payload = aiohttp.FormData()
    payload.add_field("base64Image", f"data:image/jpeg;base64,{base64_img}")
    payload.add_field("language", lang)
    payload.add_field("isOverlayRequired", "false")

    headers = {"apikey": api_key}

    try:
        async with http_session.post(url, data=payload, headers=headers) as resp:
            data = await resp.json()
            if data.get("OCRExitCode") != 1:
                return f"[OCR.space Error: {data.get('ErrorMessage', 'unknown')}]"
            results = data.get("ParsedResults", [])
            if not results:
                return ""
            return results[0].get("ParsedText", "").replace("\r\n", "").replace("\n", "")
    except Exception as e:
        return f"[OCR.space Error: {str(e)}]"

async def call_openai(base64_img: str, openai_cfg: dict) -> str:
    api_key = openai_cfg.get("apiKey", "")
    if not api_key:
        return "[OpenAI Error: API Key 未配置]"
    base_url = openai_cfg.get("baseUrl", "https://api.openai.com/v1").rstrip("/")
    model = openai_cfg.get("model", "gpt-4o-mini")

    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "提取图片中的所有文字，只输出文字内容，不加任何解释："},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
        ]}],
        "max_tokens": 1000
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        async with http_session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            if "error" in data:
                return f"[OpenAI Error: {data['error'].get('message', 'unknown')}]"
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[OpenAI Error: {str(e)}]"

def _get_paddle_ocr():
    """针对 M1 Pro 极速优化的初始化 (适配 PaddleOCR 3.5.0)"""
    global _paddle_ocr_instance
    if _paddle_ocr_instance is None:
        try:
            import paddle
            # 强制开启 CPU 加速
            paddle.set_flags({'FLAGS_use_mkldnn': True})
        except Exception:
            pass

        from paddleocr import PaddleOCR
        # 强制使用轻量级 mobile 模型，并进一步降低分辨率
        _paddle_ocr_instance = PaddleOCR(
            lang='ch',
            ocr_version='PP-OCRv4',
            text_det_limit_side_len=480,       # 从 640 降至 480，大幅提速
            text_recognition_batch_size=1,     # 单帧识别不需要 batch，设为 1 降低首字延迟
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,           # 确保关闭文档矫正（很慢）
            use_textline_orientation=False     # 确保关闭文字方向检测
        )
    return _paddle_ocr_instance

async def call_paddle(base64_img: str) -> str:
    """使用 OpenCV 极速解码 + PaddleOCR 识别"""
    try:
        import numpy as np
        import cv2
    except ImportError as e:
        return f"[PaddleOCR Error: 缺少依赖 {e.name}]"

    try:
        ocr = _get_paddle_ocr()
        # 使用 OpenCV 解码，比 PIL 快得多
        img_bytes = base64.b64decode(base64_img)
        nparray = np.frombuffer(img_bytes, np.uint8)
        img_array = cv2.imdecode(nparray, cv2.IMREAD_COLOR)

        if img_array is None:
            return "[PaddleOCR Error: 图像解码失败]"

        loop = asyncio.get_running_loop()
        # 执行识别
        result = await loop.run_in_executor(ocr_executor, lambda: ocr.predict(img_array))

        texts = []
        if result:
            # 适配 3.5.0 的返回格式
            for item in result:
                if "rec_texts" in item:
                    texts.extend(item["rec_texts"])
        return "".join(texts)
    except Exception as e:
        return f"[PaddleOCR Error: {str(e)}]"

@app.post("/api/ocr-test")
async def ocr_test():
    """测试当前 OCR 引擎连通性"""
    cfg = get_ocr_config()
    provider = cfg["ocr"].get("provider", "ollama")
    result = {"provider": provider, "ok": False, "message": ""}

    try:
        if provider == "ollama":
            ollama_cfg = cfg["ocr"].get("ollama", {})
            base_url = ollama_cfg.get("baseUrl", "http://localhost:11434")
            async with http_session.get(f"{base_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    result["ok"] = True
                    result["message"] = f"Ollama 在线，模型: {ollama_cfg.get('model', 'glm-ocr')}"
                else:
                    result["message"] = f"Ollama 返回 {resp.status}"
        elif provider == "baidu":
            baidu_cfg = cfg["ocr"].get("baidu", {})
            if not baidu_cfg.get("apiKey"):
                result["message"] = "API Key 未配置"
            else:
                token = await get_baidu_token(baidu_cfg["apiKey"], baidu_cfg.get("secretKey", ""))
                result["ok"] = bool(token)
                result["message"] = "百度 OCR 连接成功" if token else "获取 access_token 失败"
        elif provider == "ocrspace":
            ocrspace_cfg = cfg["ocr"].get("ocrspace", {})
            if not ocrspace_cfg.get("apiKey"):
                result["message"] = "API Key 未配置"
            else:
                result["ok"] = True
                result["message"] = "OCR.space 已配置"
        elif provider == "openai":
            openai_cfg = cfg["ocr"].get("openai", {})
            if not openai_cfg.get("apiKey"):
                result["message"] = "API Key 未配置"
            else:
                result["ok"] = True
                result["message"] = f"OpenAI 已配置，模型: {openai_cfg.get('model', 'gpt-4o-mini')}"
        elif provider == "paddle":
            try:
                import paddleocr
                result["ok"] = True
                result["message"] = f"PaddleOCR 已安装，版本: {paddleocr.__version__}"
            except ImportError:
                result["message"] = "PaddleOCR 未安装，请运行: pip install paddleocr"
    except Exception as e:
        result["message"] = str(e)

    return result

@app.get("/api/config")
async def get_config():
    return JSONResponse(load_json(CONFIG_FILE, {}))

@app.post("/api/config")
async def save_config(request: Request):
    """保存配置（admin面板使用）"""
    try:
        new_config = await request.json()
        save_json(CONFIG_FILE, new_config)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.get("/api/targets")
async def get_companies():
    return JSONResponse(load_json(TARGETS_FILE, []))

@app.get("/api/template")
async def download_template():
    from openpyxl import Workbook
    from fastapi.responses import FileResponse
    import tempfile
    import os

    wb = Workbook()
    ws = wb.active
    ws.title = "导入模板"
    ws.append(['识别对象', '显示信息', '备注'])
    ws.append(['示例科技股份有限公司', '2024-01-15', '示例客户'])
    ws.append(['某某实业集团有限公司', '合同编号: HT-2024-001', ''])

    # 写入临时文件确保浏览器正确识别
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    wb.save(tmp.name)
    tmp.close()

    return FileResponse(
        tmp.name,
        filename="import_template.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.post("/api/upload-excel")
async def upload_excel(request: Request):
    data = await request.json()
    file_data = data.get("fileData", "")
    file_name = data.get("fileName", "").lower()
    
    try:
        header, encoded = file_data.split(",", 1)
        file_bytes = base64.b64decode(encoded)
        
        all_rows = []
        if file_name.endswith('.csv'):
            text = file_bytes.decode('utf-8', errors='replace')
            reader = csv.reader(StringIO(text))
            all_rows = list(reader)
        elif file_name.endswith('.xls'):
            return JSONResponse({"error": "不支持的 .xls 格式，请另存为 .xlsx 后再上传"}, status_code=400)
        else:
            wb = openpyxl.load_workbook(filename=BytesIO(file_bytes), data_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                # 过滤全空行并转字符串
                str_row = [str(cell).strip() if cell is not None else "" for cell in row]
                if any(str_row):
                    all_rows.append(str_row)
                    
        if not all_rows or len(all_rows) < 2:
            return JSONResponse({"error": "文件为空或缺少数据行"}, status_code=400)
            
        headers = all_rows[0]
        data_rows = all_rows[1:]
        
        name_col = -1
        info_col = -1
        info_col2 = -1
        for i, h in enumerate(headers):
            h_clean = str(h).strip().lower()
            if h_clean in NAME_ALIASES: name_col = i
            elif h_clean in INFO_ALIASES: info_col = i
            elif h_clean in INFO2_ALIASES: info_col2 = i

        preview = []
        for row in data_rows[:5]:
            item = {}
            if name_col >= 0 and name_col < len(row): item['name'] = row[name_col]
            if info_col >= 0 and info_col < len(row): item['displayInfo'] = row[info_col]
            if info_col2 >= 0 and info_col2 < len(row): item['displayInfo2'] = row[info_col2]
            preview.append(item)

        return {
            "headers": headers,
            "preview": preview,
            "totalRows": len(data_rows),
            "nameCol": name_col,
            "infoCol": info_col,
            "infoCol2": info_col2,
            "allRows": data_rows
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

def save_target_headers(headers: List[str], name_col: int, info_col: int, info_col2: int):
    """保存用户上传表格的原始表头到 config.json"""
    cfg = load_json(CONFIG_FILE, {})
    h = {
        "name": headers[name_col] if name_col >= 0 and name_col < len(headers) else "客户名称",
        "displayInfo": headers[info_col] if info_col >= 0 and info_col < len(headers) else "合同总额",
        "displayInfo2": headers[info_col2] if info_col2 >= 0 and info_col2 < len(headers) else "欠款金额"
    }
    if "ui" not in cfg:
        cfg["ui"] = {}
    cfg["ui"]["targetHeaders"] = h
    save_json(CONFIG_FILE, cfg)

@app.post("/api/import-confirm")
async def import_confirm(req: ImportConfirmReq):
    try:
        new_companies = []
        for row in req.allRows:
            name = row[req.nameCol] if req.nameCol < len(row) else ""
            if not name: continue
            info = row[req.infoCol] if (req.infoCol >= 0 and req.infoCol < len(row)) else ""
            info2 = row[req.infoCol2] if (req.infoCol2 >= 0 and req.infoCol2 < len(row)) else ""
            item = {"name": name, "displayInfo": info}
            if info2: item["displayInfo2"] = info2
            new_companies.append(item)

        # 备份原文件
        if os.path.exists(TARGETS_FILE):
            os.rename(TARGETS_FILE, TARGETS_FILE + ".bak")

        save_json(TARGETS_FILE, new_companies)

        # 保存表头映射
        if req.headers:
            save_target_headers(req.headers, req.nameCol, req.infoCol, req.infoCol2)

        return {"success": True, "count": len(new_companies)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


class TargetItem(BaseModel):
    name: str
    displayInfo: str = ""
    displayInfo2: str = ""

class TargetUpdateReq(BaseModel):
    index: int
    name: str
    displayInfo: str = ""
    displayInfo2: str = ""

@app.post("/api/targets/add")
async def add_target(item: TargetItem):
    """添加单条目标"""
    targets = load_json(TARGETS_FILE, [])
    if any(t.get("name") == item.name for t in targets):
        return JSONResponse({"error": "该名称已存在"}, status_code=400)
    targets.append({"name": item.name, "displayInfo": item.displayInfo, "displayInfo2": item.displayInfo2})
    save_json(TARGETS_FILE, targets)
    return {"success": True, "count": len(targets)}

@app.post("/api/targets/update")
async def update_target(req: TargetUpdateReq):
    """编辑指定目标"""
    targets = load_json(TARGETS_FILE, [])
    if req.index < 0 or req.index >= len(targets):
        return JSONResponse({"error": "索引越界"}, status_code=400)
    # 检查重名（排除自身）
    for i, t in enumerate(targets):
        if i != req.index and t.get("name") == req.name:
            return JSONResponse({"error": "该名称已存在"}, status_code=400)
    targets[req.index] = {"name": req.name, "displayInfo": req.displayInfo, "displayInfo2": req.displayInfo2}
    save_json(TARGETS_FILE, targets)
    return {"success": True}

@app.post("/api/targets/delete")
async def delete_target(req: TargetUpdateReq):
    """删除指定目标（只用 index）"""
    targets = load_json(TARGETS_FILE, [])
    if req.index < 0 or req.index >= len(targets):
        return JSONResponse({"error": "索引越界"}, status_code=400)
    targets.pop(req.index)
    save_json(TARGETS_FILE, targets)
    return {"success": True, "count": len(targets)}

@app.post("/api/admin-reset")
async def admin_reset():
    """管理面板强制重置：断开所有 WebSocket 连接，清理状态"""
    disconnected = 0
    for client in list(active_ws_clients):
        try:
            await client.send_json({"status": "reset", "text": "管理员已重置，请重新连接"})
            await client.close()
            disconnected += 1
        except Exception:
            pass
    active_ws_clients.clear()
    return {"success": True, "disconnected": disconnected}

@app.post("/api/targets/clear")
async def clear_targets():
    """清空所有目标（自动备份）"""
    if os.path.exists(TARGETS_FILE):
        os.rename(TARGETS_FILE, TARGETS_FILE + ".bak")
    save_json(TARGETS_FILE, [])
    return {"success": True, "count": 0}


@app.post("/api/import-merge")
async def import_merge(req: ImportConfirmReq):
    """追加导入，按 name 去重（新数据覆盖旧的 displayInfo）"""
    try:
        # 加载现有数据
        existing = load_json(TARGETS_FILE, [])
        # 用 dict 去重，name 为 key
        merged = {item["name"]: item for item in existing if "name" in item}

        added = 0
        updated = 0
        for row in req.allRows:
            name = row[req.nameCol] if req.nameCol < len(row) else ""
            if not name: continue
            info = row[req.infoCol] if (req.infoCol >= 0 and req.infoCol < len(row)) else ""
            info2 = row[req.infoCol2] if (req.infoCol2 >= 0 and req.infoCol2 < len(row)) else ""
            if name in merged:
                merged[name]["displayInfo"] = info
                if info2: merged[name]["displayInfo2"] = info2
                updated += 1
            else:
                item = {"name": name, "displayInfo": info}
                if info2: item["displayInfo2"] = info2
                merged[name] = item
                added += 1

        # 备份并保存
        if os.path.exists(TARGETS_FILE):
            os.rename(TARGETS_FILE, TARGETS_FILE + ".bak")

        result = list(merged.values())
        save_json(TARGETS_FILE, result)

        # 保存表头映射
        if req.headers:
            save_target_headers(req.headers, req.nameCol, req.infoCol, req.infoCol2)

        return {"success": True, "total": len(result), "added": added, "updated": updated}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/target-headers")
async def get_target_headers():
    """获取当前目标列表的表头标签（从 config.json 读取）"""
    cfg = load_json(CONFIG_FILE, {})
    headers = cfg.get("ui", {}).get("targetHeaders", {
        "name": "客户名称",
        "displayInfo": "合同总额",
        "displayInfo2": "欠款金额"
    })
    return headers

@app.post("/api/open-on-phone")
async def open_on_phone():
    """通过 ADB 在手机上远程打开扫描器页面"""
    try:
        target_serial = _get_adb_target()
        if not target_serial:
            return JSONResponse(
                {"status": "error", "message": "未检测到已连接的 Android 设备"},
                status_code=500
            )

        adb_prefix = ["adb", "-s", target_serial]

        # 增强稳定性：先尝试清理旧的映射，再建立新的
        subprocess.run(adb_prefix + ["reverse", "--remove-all"], capture_output=True, timeout=2)
        rev_res = subprocess.run(adb_prefix + ["reverse", f"tcp:{SERVER_PORT}", f"tcp:{SERVER_PORT}"],
                       capture_output=True, text=True, timeout=5)

        if rev_res.returncode != 0:
            logger.error(f"[adb] reverse failed on {target_serial}: {rev_res.stderr}")
        else:
            logger.info(f"[adb] reverse established on {target_serial} for port {SERVER_PORT}")

        # 用 adb shell am start 打开手机浏览器
        target_url = f"http://localhost:{SERVER_PORT}?autostart=1"
        result = subprocess.run(
            adb_prefix + ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", target_url],
            capture_output=True, text=True, timeout=5
        )

        if result.returncode == 0:
            return {"status": "success", "message": f"已在手机上打开扫描器 ({target_serial})"}
        else:
            return JSONResponse(
                {"status": "error", "message": result.stderr or "ADB 命令执行失败"},
                status_code=500
            )
    except FileNotFoundError:
        return JSONResponse(
            {"status": "error", "message": "未找到 adb 命令，请确保已安装 Android SDK"},
            status_code=500
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {"status": "error", "message": "ADB 命令超时，请检查手机连接"},
            status_code=500
        )
    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


# === REST OCR（兜底模式，用于非安全上下文的上传） ===
@app.post("/api/ocr")
async def rest_ocr(request: Request):
    data = await request.json()
    image_data = data.get("image", "")
    if "," in image_data:
        image_data = image_data.split(",")[1]

    if not image_data:
        return JSONResponse({"error": "No image data"}, status_code=400)

    # REST 端点同样使用信号量保护，防止并发压垮 Ollama
    async with ws_semaphore:
        try:
            text = await asyncio.wait_for(dispatch_ocr(image_data), timeout=60)
        except asyncio.TimeoutError:
            text = "[Timeout: OCR 引擎响应超时，请重试]"
    return {"text": text}

# ================================
# WebSocket 流式引擎（带并发控制）
# ================================
@app.websocket("/ws/ocr")
async def websocket_ocr(websocket: WebSocket):
    # 并发保护：超过上限时拒绝连接
    if len(active_ws_clients) >= MAX_WS_CONNECTIONS:
        await websocket.accept()
        await websocket.send_json({"status": "error", "text": "服务器繁忙，请稍后重试"})
        await websocket.close()
        logger.info(f"[WS] 拒绝连接：已达上限 {MAX_WS_CONNECTIONS}")
        return

    await websocket.accept()
    active_ws_clients.add(websocket)
    logger.info(f"[WS] Client connected ({len(active_ws_clients)}/{MAX_WS_CONNECTIONS})")

    consecutive_timeouts = 0
    consecutive_empty_frames = 0  # 连续空白/异常小帧计数
    frame_count = 0
    try:
        while True:
            data = await websocket.receive_text()
            frame_count += 1

            # 兼容带有 data:image/jpeg;base64, 前缀的数据
            if "," in data:
                b64_str = data.split(",")[1]
            else:
                b64_str = data

            if DEBUG_WS: logger.info(f"[WS] Frame #{frame_count} received, size={len(b64_str)} bytes")

            # 限制图片大小（base64 约 10MB 原始数据）
            if len(b64_str) > 14_000_000:
                if DEBUG_WS: logger.info(f"[WS] Frame #{frame_count} rejected: too large")
                await websocket.send_json({"status": "error", "text": "图片过大"})
                continue

            # === 关键修复：检测异常小的帧（canvas尺寸为0时产生的空白帧特征）===
            # 正常扫描帧通常在 20KB-100KB+，空白帧约 ~4KB
            if len(b64_str) < 5000:
                consecutive_empty_frames += 1
                if DEBUG_WS: logger.info(f"[WS] Frame #{frame_count} suspiciously small ({len(b64_str)} bytes), empty streak: {consecutive_empty_frames}")
                if consecutive_empty_frames >= 15:
                    await websocket.send_json({
                        "status": "error",
                        "text": "连续发送空白帧，请检查摄像头是否正常工作或刷新页面重试"
                    })
                    break
                # 发送 processing 让前端保持状态，但继续计数
                await websocket.send_json({"status": "processing", "text": ""})
                continue
            else:
                consecutive_empty_frames = 0

            # 使用信号量限制并发调用，加 60 秒超时防止卡死
            ocr_text = ""
            try:
                async with ws_semaphore:
                    t0 = time.time()
                    ocr_text = await asyncio.wait_for(dispatch_ocr(b64_str), timeout=60)
                    elapsed = int((time.time() - t0) * 1000)
                    logger.info(f"[ocr] frame=#{frame_count} time={elapsed}ms text='{ocr_text[:50]}'")
                consecutive_timeouts = 0
                if DEBUG_WS: logger.info(f"[WS] Frame #{frame_count} OCR result: '{ocr_text[:80]}...' (len={len(ocr_text)})")
            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                ocr_text = "[Timeout: OCR 引擎响应超时，请重试]"
                if DEBUG_WS: logger.info(f"[WS] Frame #{frame_count} OCR timeout")
                if consecutive_timeouts >= 3:
                    await websocket.send_json({
                        "status": "error",
                        "text": "连续多次超时，请刷新页面重试"
                    })
                    break
            except Exception as e:
                ocr_text = f"[OCR Error: {str(e)}]"
                if DEBUG_WS: logger.info(f"[WS] Frame #{frame_count} OCR exception: {e}")

            ocr_text_clean = ocr_text.replace("\n", "").replace(" ", "")

            if len(ocr_text_clean) < 2:
                # 检测结果为空时增加计数，防止无限 processing 循环
                consecutive_empty_frames += 1
                if DEBUG_WS: logger.info(f"[WS] Frame #{frame_count} sending 'processing' (text too short: '{ocr_text[:40]}'), empty streak: {consecutive_empty_frames}")
                if consecutive_empty_frames >= 20:
                    await websocket.send_json({
                        "status": "error",
                        "text": "连续识别空白内容，请调整摄像头对准合同文字"
                    })
                    break
                await websocket.send_json({
                    "status": "processing",
                    "text": ocr_text
                })
                continue
            else:
                consecutive_empty_frames = 0

            if DEBUG_WS: logger.info(f"[WS] Frame #{frame_count} sending 'success'")
            await websocket.send_json({
                "status": "success",
                "text": ocr_text
            })

    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected ({len(active_ws_clients)}/{MAX_WS_CONNECTIONS})")
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
        try:
            await websocket.close()
        except: pass
    finally:
        active_ws_clients.discard(websocket)

# === 健康检查 ===
@app.get("/health")
async def health_check():
    """检查服务及 Ollama 是否在线"""
    ollama_ok = False
    ollama_model = None
    try:
        async with http_session.get("http://localhost:11434/api/tags", timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status == 200:
                data = await resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                ollama_ok = len(models) > 0
                ollama_model = models[0] if models else None
    except Exception:
        pass

    return {
        "status": "ok",
        "ollama": {
            "online": ollama_ok,
            "model": ollama_model
        },
        "active_ws": len(active_ws_clients),
        "max_ws": MAX_WS_CONNECTIONS
    }

def _get_adb_target():
    """获取目标 ADB 设备 serial，优先 USB 设备，解决多设备冲突"""
    r = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=5)
    usb_serial = None
    wifi_serial = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serial = parts[0]
            if "usb:" in line:
                usb_serial = serial
            elif ":" in serial:
                wifi_serial = serial
            else:
                wifi_serial = serial
    return usb_serial or wifi_serial

def _get_device_wifi_ip(adb_prefix: list) -> Optional[str]:
    """通过 adb shell ip route 提取手机 WiFi IP"""
    try:
        r = subprocess.run(adb_prefix + ["shell", "ip", "route"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if "wlan0" not in line:
                continue
            parts = line.split()
            if "src" in parts:
                idx = parts.index("src")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
            if "via" in parts:
                idx = parts.index("via")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
    except Exception:
        pass
    try:
        r2 = subprocess.run(adb_prefix + ["shell", "ifconfig", "wlan0"],
                            capture_output=True, text=True, timeout=5)
        for line in r2.stdout.splitlines():
            if "inet " in line:
                ip_part = line.split()[1]
                if ":" in ip_part:
                    ip_part = ip_part.split(":")[1]
                return ip_part
    except Exception:
        pass
    return None


def _get_all_adb_devices() -> list:
    """获取所有已连接的 ADB 设备列表，自动去重（当同一手机同时存在 USB 和 WiFi 连接时）"""
    devices_dict = {}
    try:
        r = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                mode = "usb" if "usb:" in line else "wifi"
                model = ""
                for p in parts:
                    if p.startswith("model:"):
                        model = p.split(":", 1)[1]
                        break
                wifi_ip = None
                adb_prefix = ["adb", "-s", serial]
                try:
                    wifi_ip = _get_device_wifi_ip(adb_prefix)
                except Exception:
                    pass
                
                device_info = {
                    "serial": serial,
                    "mode": mode,
                    "model": model,
                    "wifi_ip": wifi_ip,
                    "status": "connected"
                }

                # 更加严谨的去重：使用 (model, wifi_ip) 作为联合键
                # 如果同一型号且 IP 相同，判定为同一台手机
                key = (model, wifi_ip) if wifi_ip else (None, serial)
                
                if key in devices_dict:
                    # 关键：优先保留物理 USB 连接，其端口转发最稳定
                    if mode == "usb":
                        devices_dict[key] = device_info
                else:
                    devices_dict[key] = device_info
                    
    except Exception as e:
        logger.error(f"[adb] enumerate failed: {e}")
    
    return list(devices_dict.values())
def _get_local_ips():
    """获取本机局域网IP地址列表（排除回环地址），带接口名和优先级排序。
    当存在 VPN/隧道/虚拟接口时，优先返回物理网卡（WiFi/以太网）的IP。
    返回: [(ip, iface_name, iface_type, priority), ...]
    """
    PRIVATE_PREFIXES = (
        '192.168.', '10.',
        '172.16.', '172.17.', '172.18.', '172.19.',
        '172.20.', '172.21.', '172.22.', '172.23.',
        '172.24.', '172.25.', '172.26.', '172.27.',
        '172.28.', '172.29.', '172.30.', '172.31.',
    )
    results = []
    seen = set()

    def _iface_priority(name):
        """接口优先级：物理网卡 > 未知 > VPN/虚拟/隧道"""
        low = ('utun', 'tun', 'tap', 'docker', 'veth', 'br-', 'lo', 'gif', 'stf', 'anpi')
        high = ('en0', 'en1', 'en2', 'en3', 'eth0', 'eth1', 'wlan0', 'wlan1', 'wlp')
        if any(name.startswith(p) for p in high):
            return 0
        if any(name.startswith(p) for p in low):
            return 2
        return 1

    def _iface_type(name):
        if name.startswith(('wlan', 'wlp', 'en')):
            return 'wifi'
        if name.startswith(('eth', 'enp')):
            return 'ethernet'
        if name.startswith(('utun', 'tun', 'tap', 'vpn')):
            return 'vpn'
        if any(name.startswith(p) for p in ('docker', 'veth', 'br-', 'lo')):
            return 'virtual'
        return 'unknown'

    def _add(ip, iface):
        if ip in seen or ip == '127.0.0.1':
            return
        if not ip.startswith(PRIVATE_PREFIXES):
            return
        seen.add(ip)
        results.append((ip, iface, _iface_type(iface), _iface_priority(iface)))

    # 方法1: ip addr（现代 Linux）
    try:
        result = subprocess.run(['ip', 'addr'], capture_output=True, text=True)
        current_iface = None
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and not line.startswith('inet'):
                # 例如 "2: en0: <BROADCAST...>"
                m = line.split(':')
                if len(m) >= 2:
                    current_iface = m[1].strip()
            elif 'inet ' in line and current_iface:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == 'inet' and i + 1 < len(parts):
                        ip = parts[i + 1].split('/')[0]
                        _add(ip, current_iface)
    except Exception:
        pass

    # 方法2: ifconfig（macOS / 旧 Linux）
    if not results:
        try:
            result = subprocess.run(['ifconfig'], capture_output=True, text=True)
            current_iface = None
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                iface_part = line.split(':')[0]
                if line[0].isalnum() and ':' in line and ' ' not in iface_part:
                    # 例如 "en0: flags=..."
                    current_iface = iface_part.strip()
                elif 'inet ' in line and current_iface:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == 'inet' and i + 1 < len(parts):
                            ip = parts[i + 1]
                            if ':' in ip:
                                ip = ip.split(':')[1]
                            _add(ip, current_iface)
        except Exception:
            pass

    # 方法3: UDP socket 兜底
    if not results:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            try:
                s.connect(('10.254.254.254', 1))
                ip = s.getsockname()[0]
                _add(ip, 'default')
            except Exception:
                pass
            finally:
                s.close()
        except Exception:
            pass

    # 按优先级排序（物理网卡优先）
    results.sort(key=lambda x: x[3])
    return results

@app.get("/api/network-info")
async def network_info():
    """返回本机局域网IP，供手机WiFi模式连接使用"""
    iface_list = _get_local_ips()  # [(ip, name, type, priority), ...]
    plain_ips = [r[0] for r in iface_list]
    best_ip = plain_ips[0] if plain_ips else None
    return {
        "port": SERVER_PORT,
        "local_ips": plain_ips,
        "interfaces": [
            {"ip": r[0], "name": r[1], "type": r[2]} for r in iface_list
        ],
        "wifi_url": f"http://{best_ip}:{SERVER_PORT}" if best_ip else None,
        "usb_url": f"http://localhost:{SERVER_PORT}"
    }

@app.get("/api/qr-code")
async def qr_code(data: str):
    """服务端生成 QR 码 PNG（避免依赖外部 CDN，支持纯内网环境）"""
    try:
        import qrcode
        from fastapi.responses import StreamingResponse
        img = qrcode.make(data)
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")
    except ImportError:
        return JSONResponse(
            {"error": "qrcode module not installed. Run: pip install qrcode[pil]"},
            status_code=503
        )

@app.get("/api/adb-wifi-status")
async def adb_wifi_status():
    """检查 ADB 连接状态和手机 WiFi IP"""
    result = {"connected": False, "usb_device": None, "wifi_ip": None, "mode": None}
    try:
        r = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=5)
        target_serial = None
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                target_serial = serial
                if "usb:" in line:
                    result["usb_device"] = serial
                    result["mode"] = "usb"
                else:
                    result["mode"] = "wifi"
                result["connected"] = True
                break
        if result["connected"] and target_serial:
            wifi_ip = _get_device_wifi_ip(["adb", "-s", target_serial])
            if wifi_ip:
                result["wifi_ip"] = wifi_ip
    except Exception as e:
        result["error"] = str(e)
    return result


@app.post("/api/adb-wifi-start")
async def adb_wifi_start():
    """开启 ADB 网络模式 (adb tcpip 5555)"""
    try:
        target = _get_adb_target()
        if not target:
            return {"status": "error", "message": "未检测到已连接的 Android 设备"}
        adb_prefix = ["adb", "-s", target]
        r = subprocess.run(adb_prefix + ["tcpip", "5555"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            # tcpip 后 ADB daemon 重启，连接短暂断开，等 2 秒再获取 IP
            import time; await asyncio.sleep(2)
            wifi_ip = _get_device_wifi_ip(adb_prefix)
            global adb_wifi_ip_cache
            adb_wifi_ip_cache = wifi_ip
            return {"status": "success", "message": "ADB 网络模式已开启，请拔掉数据线", "wifi_ip": wifi_ip, "port": 5555}
        else:
            return {"status": "error", "message": r.stderr or "adb tcpip 失败"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/adb-wifi-connect")
async def adb_wifi_connect(req: AdbWifiConnectReq):
    """通过 WiFi 连接 ADB 并设置端口映射。
    拔线后 _get_adb_target() 会返回 None，因此不再依赖它检测设备，
    而是直接 trust 前端传来的 wifi_ip，adb connect 后再 reverse。
    """
    wifi_ip = req.wifi_ip
    if not wifi_ip:
        target = _get_adb_target()
        if target:
            wifi_ip = _get_device_wifi_ip(["adb", "-s", target])
    # 兜底：使用 tcpip 时缓存的 IP
    if not wifi_ip and adb_wifi_ip_cache:
        wifi_ip = adb_wifi_ip_cache
    if not wifi_ip:
        return {"status": "error", "message": "缺少手机 WiFi IP，请重新开启无线调试"}

    try:
        # 连接 WiFi ADB（拔线后这是唯一可靠的连接方式）
        wifi_target = f"{wifi_ip}:5555"
        r1 = subprocess.run(["adb", "connect", wifi_target], capture_output=True, text=True, timeout=10)
        out = r1.stdout.lower()
        # 兼容中英文输出: "connected to" / "already connected" / "已连接到"
        if not any(k in out for k in ("connected", "already", "已连接")):
            return {"status": "error", "message": f"连接失败: {r1.stdout or r1.stderr}"}

        # 设置端口映射（使用 WiFi serial，确保 USB 拔掉后仍然有效）
        wifi_prefix = ["adb", "-s", wifi_target]
        r2 = subprocess.run(wifi_prefix + ["reverse", f"tcp:{SERVER_PORT}", f"tcp:{SERVER_PORT}"],
                            capture_output=True, text=True, timeout=5)

        return {
            "status": "success",
            "message": "WiFi ADB 连接成功",
            "wifi_ip": wifi_ip,
            "phone_url": f"http://localhost:{SERVER_PORT}",
            "adb_output": r1.stdout.strip()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}



# === 多设备 ADB 管理 ===
@app.get("/api/adb-devices")
async def adb_devices_list():
    """列出所有已连接的 ADB 设备"""
    devices = _get_all_adb_devices()
    return {"devices": devices, "count": len(devices)}

@app.post("/api/adb-wifi-start-all")
async def adb_wifi_start_all():
    """批量开启所有 USB 设备的 ADB 网络模式"""
    devices = _get_all_adb_devices()
    usb_devices = [d for d in devices if d["mode"] == "usb"]
    if not usb_devices:
        return {"status": "error", "message": "未检测到 USB 连接的设备"}

    results = []
    for d in usb_devices:
        serial = d["serial"]
        try:
            r = subprocess.run(["adb", "-s", serial, "tcpip", "5555"],
                             capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                await asyncio.sleep(2)
                wifi_ip = _get_device_wifi_ip(["adb", "-s", serial])
                results.append({"serial": serial, "status": "success", "wifi_ip": wifi_ip})
                logger.info(f"[adb] tcpip 5555 OK for {serial}, wifi_ip={wifi_ip}")
            else:
                results.append({"serial": serial, "status": "error", "message": r.stderr})
                logger.error(f"[adb] tcpip 5555 failed for {serial}: {r.stderr}")
        except Exception as e:
            results.append({"serial": serial, "status": "error", "message": str(e)})
            logger.error(f"[adb] tcpip exception for {serial}: {e}")

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "status": "success" if success_count > 0 else "error",
        "message": f"已开启 {success_count}/{len(usb_devices)} 台设备的网络模式",
        "results": results
    }

@app.post("/api/adb-wifi-connect-all")
async def adb_wifi_connect_all():
    """批量连接所有已知 WiFi 设备并设置端口映射"""
    devices = _get_all_adb_devices()
    # 收集所有设备的 WiFi IP（包括已连接的 WiFi 设备和缓存中的 USB 设备 IP）
    targets = []
    for d in devices:
        if d["mode"] == "wifi" and ":" in d["serial"]:
            # 已通过 WiFi 连接的设备，确保 reverse 存在
            targets.append({"serial": d["serial"], "wifi_ip": d["serial"].split(":")[0]})
        elif d["wifi_ip"]:
            # USB 设备但已知 WiFi IP
            targets.append({"serial": d["serial"], "wifi_ip": d["wifi_ip"]})

    if not targets:
        return {"status": "error", "message": "未发现可连接的 WiFi 设备（请先开启无线调试）"}

    results = []
    for t in targets:
        wifi_ip = t["wifi_ip"]
        wifi_target = f"{wifi_ip}:5555"
        try:
            # Connect
            r1 = subprocess.run(["adb", "connect", wifi_target],
                              capture_output=True, text=True, timeout=10)
            out = r1.stdout.lower()
            connected = any(k in out for k in ("connected", "already", "已连接"))
            
            # Reverse
            r2 = subprocess.run(["adb", "-s", wifi_target, "reverse", f"tcp:{SERVER_PORT}", f"tcp:{SERVER_PORT}"],
                              capture_output=True, text=True, timeout=5)
            
            results.append({
                "wifi_ip": wifi_ip,
                "connect": "ok" if connected else r1.stdout.strip(),
                "reverse": "ok" if r2.returncode == 0 else r2.stderr.strip()
            })
            logger.info(f"[adb] connect+reverse {wifi_target}: connect={connected} reverse={r2.returncode==0}")
        except Exception as e:
            results.append({"wifi_ip": wifi_ip, "connect": "error", "message": str(e)})
            logger.error(f"[adb] connect+reverse {wifi_target} failed: {e}")

    ok_count = sum(1 for r in results if r.get("connect") == "ok")
    return {
        "status": "success" if ok_count > 0 else "error",
        "message": f"已连接 {ok_count}/{len(targets)} 台设备",
        "results": results
    }

@app.post("/api/open-on-phone/{serial}")
async def open_on_phone_by_serial(serial: str):
    """在指定设备上打开扫描器页面"""
    try:
        adb_prefix = ["adb", "-s", serial]
        
        # 清理并重建映射
        subprocess.run(adb_prefix + ["reverse", "--remove-all"], capture_output=True, timeout=2)
        rev_res = subprocess.run(adb_prefix + ["reverse", f"tcp:{SERVER_PORT}", f"tcp:{SERVER_PORT}"],
                       capture_output=True, text=True, timeout=5)
        
        target_url = f"http://localhost:{SERVER_PORT}?autostart=1"
        result = subprocess.run(
            adb_prefix + ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", target_url],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            logger.info(f"[adb] opened browser on {serial}")
            return {"status": "success", "message": f"已在设备 {serial} 上打开扫描器"}
        else:
            return JSONResponse({"status": "error", "message": result.stderr}, status_code=500)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/api/model-status")
async def model_status():
    """检查当前 OCR 引擎状态"""
    cfg = get_ocr_config()
    provider = cfg["ocr"].get("provider", "ollama")
    result = {"provider": provider, "ready": False, "message": ""}

    try:
        if provider == "ollama":
            ollama_cfg = cfg["ocr"].get("ollama", {})
            target_model = ollama_cfg.get("model", "glm-ocr")
            base_url = ollama_cfg.get("baseUrl", "http://localhost:11434")
            async with http_session.get(f"{base_url}/api/ps", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    loaded = [m.get("name", "") for m in data.get("models", [])]
                    if any(target_model in n for n in loaded):
                        result["ready"] = True
                        result["message"] = f"{target_model} loaded"
                    else:
                        result["message"] = "Standby"
        elif provider == "baidu":
            baidu_cfg = cfg["ocr"].get("baidu", {})
            result["ready"] = bool(baidu_cfg.get("apiKey"))
            result["message"] = "已配置" if result["ready"] else "未配置"
        elif provider == "ocrspace":
            ocrspace_cfg = cfg["ocr"].get("ocrspace", {})
            result["ready"] = bool(ocrspace_cfg.get("apiKey"))
            result["message"] = "已配置" if result["ready"] else "未配置"
        elif provider == "openai":
            openai_cfg = cfg["ocr"].get("openai", {})
            result["ready"] = bool(openai_cfg.get("apiKey"))
            result["message"] = "已配置" if result["ready"] else "未配置"
        elif provider == "paddle":
            try:
                import paddleocr
                result["ready"] = True
                result["message"] = f"PaddleOCR {paddleocr.__version__} 就绪"
            except ImportError:
                result["message"] = "未安装 paddleocr"
    except Exception:
        result["message"] = "连接失败"

    return result

@app.post("/api/model-load")
async def model_load():
    """触发 Ollama 模型加载（异步后台执行）"""
    cfg = get_ocr_config()
    provider = cfg["ocr"].get("provider", "ollama")
    if provider != "ollama":
        return {"ok": True, "message": "非 Ollama 引擎，无需加载"}

    ollama_cfg = cfg["ocr"].get("ollama", {})
    target_model = ollama_cfg.get("model", "glm-ocr")
    base_url = ollama_cfg.get("baseUrl", "http://localhost:11434")
    keep_alive = ollama_cfg.get("keepAlive", "10m")

    # 先检查是否已加载
    try:
        async with http_session.get(f"{base_url}/api/ps", timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status == 200:
                data = await resp.json()
                loaded = [m.get("name", "") for m in data.get("models", [])]
                if any(target_model in n for n in loaded):
                    return {"ok": True, "message": f"{target_model} 已在内存中", "already_loaded": True}
    except Exception:
        pass

    # 后台启动加载
    asyncio.create_task(_do_model_load(base_url, target_model, keep_alive))
    return {"ok": True, "message": f"正在加载 {target_model}...", "already_loaded": False}

async def _do_model_load(base_url: str, model: str, keep_alive: str):
    """后台加载模型到 GPU/内存"""
    timeout = aiohttp.ClientTimeout(total=120, sock_read=30, connect=10)
    try:
        url = f"{base_url.rstrip('/')}/api/generate"
        payload = {"model": model, "prompt": "hi", "stream": False, "keep_alive": keep_alive}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    logger.info(f"✅ 模型 {model} 加载完成")
                else:
                    logger.warning(f"⚠️ 模型加载失败: HTTP {resp.status}")
    except asyncio.TimeoutError:
        logger.warning(f"⚠️ 模型加载超时，模型可能已卡死")
    except Exception as e:
        logger.warning(f"⚠️ 模型加载异常: {e}")

# === 日志 API ===
@app.get("/api/logs")
async def get_logs(lines: int = 100):
    """读取最近 N 行日志"""
    try:
        if not os.path.exists(LOG_FILE):
            return {"logs": "", "lines": 0}
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        recent = all_lines[-lines:]
        return {"logs": "".join(recent), "lines": len(recent)}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}", "lines": 0}

@app.get("/api/logs/download")
async def download_logs():
    """下载完整日志文件"""
    if os.path.exists(LOG_FILE):
        return FileResponse(LOG_FILE, filename="scanner.log", media_type="text/plain")
    return JSONResponse({"error": "Log file not found"}, status_code=404)

# === 根路由（显式声明，优先于 StaticFiles mount） ===
@app.get("/")
async def root():
    return FileResponse(
        os.path.join(BASE_DIR, "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )

# === 静态文件（禁用 HTML/JS/CSS 缓存，防止手机浏览器缓存旧版本） ===
class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.mount("/", NoCacheStaticFiles(directory=BASE_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    logger.info(f"🚀 FastAPI Server starting on http://localhost:{SERVER_PORT}")
    uvicorn.run("server:app", host="0.0.0.0", port=SERVER_PORT, log_level="info")

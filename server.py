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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import openpyxl
import aiohttp

# === 全局 aiohttp Session（复用连接池，避免每次请求创建新连接） ===
http_session: Optional[aiohttp.ClientSession] = None

async def _reset_http_session():
    """重置 aiohttp session，清理可能卡死的连接池"""
    global http_session
    if http_session and not http_session.closed:
        await http_session.close()
    timeout = aiohttp.ClientTimeout(total=60, connect=10)
    http_session = aiohttp.ClientSession(timeout=timeout)
    print("🔄 aiohttp Session 已重置（清理死连接）")

# === WebSocket 并发控制 ===
MAX_WS_CONNECTIONS = 3  # 最多 3 个 WebSocket 客户端连接
MAX_OLLAMA_CONCURRENT = 1  # 同时只允许 1 个 Ollama 推理请求（保护其他模型）
ws_semaphore: Optional[asyncio.Semaphore] = None
active_ws_clients: Set[WebSocket] = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用生命周期：启动时创建 HTTP Session，预热模型，关闭时释放"""
    global http_session, ws_semaphore
    timeout = aiohttp.ClientTimeout(total=60, connect=10)
    http_session = aiohttp.ClientSession(timeout=timeout)
    ws_semaphore = asyncio.Semaphore(MAX_OLLAMA_CONCURRENT)
    print("✅ aiohttp Session 已创建")
    print(f"✅ Ollama 并发限制: {MAX_OLLAMA_CONCURRENT}")

    # 预热 GLM-OCR 模型（加载到显存/内存）
    asyncio.create_task(warmup_model())

    yield
    await http_session.close()
    print("🔚 aiohttp Session 已关闭")

async def warmup_model():
    """启动后异步预热模型（仅 Ollama 引擎，不抢占其他模型显存）"""
    try:
        cfg = get_ocr_config()
        if cfg["ocr"].get("provider", "ollama") != "ollama":
            print("⏭️ 当前非 Ollama 引擎，跳过预热")
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
                    print(f"⏭️ 检测到其他模型运行中 ({', '.join(other_loaded)})，跳过预热避免抢占显存")
                    return
                if any(model in n for n in loaded):
                    print(f"✅ {model} 已在内存中，无需预热")
                    return

        print(f"⏳ 正在预热模型 {model}...")
        url = f"{base_url.rstrip('/')}/api/generate"
        payload = {"model": model, "prompt": "hi", "stream": False, "keep_alive": ollama_cfg.get("keepAlive", "10m")}
        async with http_session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status == 200:
                print(f"✅ 模型 {model} 预热完成，已加载到内存")
            else:
                print(f"⚠️ 模型预热失败: HTTP {resp.status}")
    except Exception as e:
        print(f"⚠️ 模型预热异常: {e}")

app = FastAPI(title="Contract Scanner AI", lifespan=lifespan)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
TARGETS_FILE = os.path.join(BASE_DIR, "targets.json")

NAME_ALIASES = {'识别对象', '公司名称', '公司名', '名称', '公司', '目标', '对象', 'company', 'name', 'target', '企业名称', '单位名称', '客户名称'}
INFO_ALIASES = {'显示信息', '附加信息', '备注', '日期', '开单日期', '合同编号', 'info', 'note', 'date', '说明'}
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

def load_json(filepath, default_val):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
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
            "openai": {"apiKey": "", "model": "gpt-4o-mini", "baseUrl": "https://api.openai.com/v1"}
        }
        save_json(CONFIG_FILE, cfg)
    # 确保 ocrspace 配置块存在（向前兼容）
    if "ocrspace" not in cfg.get("ocr", {}):
        cfg["ocr"]["ocrspace"] = {"apiKey": "", "language": "chs"}
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
    payload = {
        "model": model,
        "prompt": "提取图片中的所有文字，不要加任何解释或格式：",
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
                    print(f"[Ollama] 第 {attempt + 1} 次请求超时，3 秒后重试...")
                    await asyncio.sleep(3)
                    continue
                return "[Timeout: Ollama 响应超时，请检查模型是否卡死]"
            except Exception as e:
                return f"[Ollama Error: {str(e)}]"

async def call_baidu(base64_img: str, baidu_cfg: dict) -> str:
    api_key = baidu_cfg.get("apiKey", "")
    secret_key = baidu_cfg.get("secretKey", "")
    if not api_key or not secret_key:
        return "[Baidu Error: API Key 未配置]"

    try:
        token = await get_baidu_token(api_key, secret_key)
        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token={token}"
        params = {"image": base64_img, "language_type": "CHN_ENG"}
        async with http_session.post(url, data=params) as resp:
            data = await resp.json()
            if "error_code" in data:
                return f"[Baidu Error: {data.get('error_msg', data['error_code'])}]"
            words = [w.get("words", "") for w in data.get("words_result", [])]
            return "".join(words)
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
    import subprocess
    try:
        # 先确保 adb reverse 已建立
        subprocess.run(["adb", "reverse", "tcp:8080", "tcp:8080"],
                       capture_output=True, timeout=5)
        # 用 adb shell am start 打开手机浏览器
        result = subprocess.run(
            ["adb", "shell", "am", "start", "-a", "android.intent.action.VIEW",
             "-d", "http://localhost:8080?autostart=1"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return {"status": "success", "message": "已在手机上打开扫描器"}
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
        print(f"[WS] 拒绝连接：已达上限 {MAX_WS_CONNECTIONS}")
        return

    await websocket.accept()
    active_ws_clients.add(websocket)
    print(f"[WS] Client connected ({len(active_ws_clients)}/{MAX_WS_CONNECTIONS})")

    consecutive_timeouts = 0
    try:
        while True:
            data = await websocket.receive_text()

            # 兼容带有 data:image/jpeg;base64, 前缀的数据
            if "," in data:
                b64_str = data.split(",")[1]
            else:
                b64_str = data

            # 限制图片大小（base64 约 10MB 原始数据）
            if len(b64_str) > 14_000_000:
                await websocket.send_json({"status": "error", "text": "图片过大"})
                continue

            # 使用信号量限制并发调用，加 60 秒超时防止卡死
            async with ws_semaphore:
                try:
                    ocr_text = await asyncio.wait_for(dispatch_ocr(b64_str), timeout=60)
                    consecutive_timeouts = 0
                except asyncio.TimeoutError:
                    consecutive_timeouts += 1
                    ocr_text = "[Timeout: OCR 引擎响应超时，请重试]"
                    if consecutive_timeouts >= 3:
                        await websocket.send_json({
                            "status": "error",
                            "text": "连续多次超时，请刷新页面重试"
                        })
                        break
            ocr_text_clean = ocr_text.replace("\n", "").replace(" ", "")

            if len(ocr_text_clean) < 2:
                await websocket.send_json({
                    "status": "processing",
                    "text": ocr_text
                })
                continue

            await websocket.send_json({
                "status": "success",
                "text": ocr_text
            })

    except WebSocketDisconnect:
        print(f"[WS] Client disconnected ({len(active_ws_clients)}/{MAX_WS_CONNECTIONS})")
    except Exception as e:
        print(f"[WS] Error: {e}")
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

def _get_local_ips():
    """获取本机局域网IP地址列表（排除回环地址）"""
    ips = []
    try:
        import subprocess
        result = subprocess.run(['ifconfig'], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if 'inet ' in line and '127.0.0.1' not in line:
                parts = line.strip().split()
                for i, p in enumerate(parts):
                    if p == 'inet' and i + 1 < len(parts):
                        ip = parts[i + 1]
                        if ':' in ip:
                            ip = ip.split(':')[1]
                        if ip.startswith(('192.168.', '10.', '172.16.', '172.17.', '172.18.', '172.19.', '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.', '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.')):
                            ips.append(ip)
    except Exception:
        pass
    # fallback
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            try:
                s.connect(('10.254.254.254', 1))
                ip = s.getsockname()[0]
                if ip != '127.0.0.1':
                    ips.append(ip)
            except Exception:
                pass
            finally:
                s.close()
        except Exception:
            pass
    return list(dict.fromkeys(ips))  # 去重保持顺序

@app.get("/api/network-info")
async def network_info():
    """返回本机局域网IP，供手机WiFi模式连接使用"""
    ips = _get_local_ips()
    return {
        "port": 8080,
        "local_ips": ips,
        "wifi_url": f"http://{ips[0]}:8080" if ips else None,
        "usb_url": "http://localhost:8080"
    }

@app.get("/api/adb-wifi-status")
async def adb_wifi_status():
    """检查 ADB 连接状态和手机 WiFi IP"""
    result = {"connected": False, "usb_device": None, "wifi_ip": None, "mode": None}
    try:
        # 检查是否有 USB 设备
        r = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=5)
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and not l.strip().startswith("List")]
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                serial = parts[0]
                status = parts[1]
                if status == "device":
                    if "usb:" in line:
                        result["usb_device"] = serial
                        result["mode"] = "usb"
                    else:
                        result["mode"] = "wifi"
                    result["connected"] = True
                    break
        # 获取手机 WiFi IP
        if result["connected"]:
            r2 = subprocess.run(["adb", "shell", "ip", "route"], capture_output=True, text=True, timeout=5)
            for line in r2.stdout.splitlines():
                if "wlan0" in line or "wifi" in line.lower():
                    parts = line.split()
                    if len(parts) >= 9:
                        result["wifi_ip"] = parts[8]
                        break
            # fallback
            if not result["wifi_ip"]:
                r3 = subprocess.run(["adb", "shell", "ifconfig", "wlan0"], capture_output=True, text=True, timeout=5)
                for line in r3.stdout.splitlines():
                    if "inet " in line:
                        ip_part = line.split()[1]
                        if ":" in ip_part:
                            ip_part = ip_part.split(":")[1]
                        result["wifi_ip"] = ip_part
                        break
    except Exception as e:
        result["error"] = str(e)
    return result


@app.post("/api/adb-wifi-start")
async def adb_wifi_start():
    """开启 ADB 网络模式 (adb tcpip 5555)"""
    try:
        r = subprocess.run(["adb", "tcpip", "5555"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            # 获取手机 WiFi IP
            wifi_ip = None
            try:
                r2 = subprocess.run(["adb", "shell", "ip", "route"], capture_output=True, text=True, timeout=5)
                for line in r2.stdout.splitlines():
                    if "wlan0" in line:
                        parts = line.split()
                        if len(parts) >= 9:
                            wifi_ip = parts[8]
                            break
            except Exception:
                pass
            return {"status": "success", "message": "ADB 网络模式已开启，请拔掉数据线", "wifi_ip": wifi_ip, "port": 5555}
        else:
            return {"status": "error", "message": r.stderr or "adb tcpip 失败"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/adb-wifi-connect")
async def adb_wifi_connect():
    """通过 WiFi 连接 ADB 并设置端口映射"""
    try:
        # 先获取手机 WiFi IP
        wifi_ip = None
        try:
            r = subprocess.run(["adb", "shell", "ip", "route"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                if "wlan0" in line:
                    parts = line.split()
                    if len(parts) >= 9:
                        wifi_ip = parts[8]
                        break
        except Exception:
            pass

        if not wifi_ip:
            return {"status": "error", "message": "无法获取手机 WiFi IP，请确保手机已连接 WiFi"}

        # 连接 WiFi ADB
        r1 = subprocess.run(["adb", "connect", f"{wifi_ip}:5555"], capture_output=True, text=True, timeout=10)
        if "connected" not in r1.stdout.lower() and "already" not in r1.stdout.lower():
            return {"status": "error", "message": f"连接失败: {r1.stdout or r1.stderr}"}

        # 设置端口映射
        r2 = subprocess.run(["adb", "reverse", "tcp:8080", "tcp:8080"], capture_output=True, text=True, timeout=5)

        return {
            "status": "success",
            "message": "WiFi ADB 连接成功",
            "wifi_ip": wifi_ip,
            "phone_url": "http://localhost:8080",
            "adb_output": r1.stdout.strip()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
                    print(f"✅ 模型 {model} 加载完成")
                else:
                    print(f"⚠️ 模型加载失败: HTTP {resp.status}")
    except asyncio.TimeoutError:
        print(f"⚠️ 模型加载超时，模型可能已卡死")
    except Exception as e:
        print(f"⚠️ 模型加载异常: {e}")

# === 根路由（显式声明，优先于 StaticFiles mount） ===
@app.get("/")
async def root():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

# === 静态文件（StaticFiles 自带路径穿越防护） ===
# FastAPI 显式路由优先于 mount，无需额外过滤
app.mount("/", StaticFiles(directory=BASE_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    print("🚀 FastAPI Server starting on http://localhost:8080")
    uvicorn.run("server:app", host="0.0.0.0", port=8080, log_level="info")

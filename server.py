import os
import json
import base64
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from io import BytesIO, StringIO
import csv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import openpyxl
import aiohttp

# === 全局 aiohttp Session（复用连接池，避免每次请求创建新连接） ===
http_session: Optional[aiohttp.ClientSession] = None

# === 静态文件白名单（防路径穿越） ===
ALLOWED_EXTENSIONS = {'.html', '.js', '.css', '.json', '.png', '.jpg', '.jpeg', '.ico', '.svg', '.woff', '.woff2', '.ttf'}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用生命周期：启动时创建 HTTP Session，关闭时释放"""
    global http_session
    timeout = aiohttp.ClientTimeout(total=60, connect=10)
    http_session = aiohttp.ClientSession(timeout=timeout)
    print("✅ aiohttp Session 已创建")
    yield
    await http_session.close()
    print("🔚 aiohttp Session 已关闭")

app = FastAPI(title="Contract Scanner AI", lifespan=lifespan)

CONFIG_FILE = "config.json"
TARGETS_FILE = "targets.json"

NAME_ALIASES = {'识别对象', '公司名称', '公司名', '名称', '公司', '目标', '对象', 'company', 'name', 'target', '企业名称', '单位名称', '客户名称'}
INFO_ALIASES = {'显示信息', '附加信息', '备注', '日期', '开单日期', '合同编号', 'info', 'note', 'date', '说明'}

# Pydantic models
class ExcelUploadResult(BaseModel):
    headers: List[str]
    preview: List[dict]
    totalRows: int
    nameCol: int
    infoCol: int
    allRows: List[List[Any]]

class ImportConfirmReq(BaseModel):
    nameCol: int
    infoCol: int
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
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
    from fastapi.responses import StreamingResponse
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = "导入模板"
    ws.append(['识别对象', '显示信息', '备注'])
    ws.append(['示例科技股份有限公司', '2024-01-15', '示例客户'])
    ws.append(['某某实业集团有限公司', '合同编号: HT-2024-001', ''])
    
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="import_template.xlsx"',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    }
    return StreamingResponse(stream, headers=headers)

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
        for i, h in enumerate(headers):
            h_clean = str(h).strip().lower()
            if h_clean in NAME_ALIASES: name_col = i
            elif h_clean in INFO_ALIASES: info_col = i
            
        preview = []
        for row in data_rows[:5]:
            item = {}
            if name_col >= 0 and name_col < len(row): item['name'] = row[name_col]
            if info_col >= 0 and info_col < len(row): item['displayInfo'] = row[info_col]
            preview.append(item)
            
        return {
            "headers": headers,
            "preview": preview,
            "totalRows": len(data_rows),
            "nameCol": name_col,
            "infoCol": info_col,
            "allRows": data_rows
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/import-confirm")
async def import_confirm(req: ImportConfirmReq):
    try:
        new_companies = []
        for row in req.allRows:
            name = row[req.nameCol] if req.nameCol < len(row) else ""
            if not name: continue
            info = row[req.infoCol] if (req.infoCol >= 0 and req.infoCol < len(row)) else ""
            new_companies.append({
                "name": name,
                "displayInfo": info
            })
            
        if os.path.exists(TARGETS_FILE):
            os.rename(TARGETS_FILE, TARGETS_FILE + ".bak")
            
        save_json(TARGETS_FILE, new_companies)
        return {"success": True, "count": len(new_companies)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

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

async def call_ollama(base64_img: str) -> str:
    """Async wrapper for calling Ollama GLM-OCR（使用全局 Session 复用连接）"""
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "glm-ocr",
        "prompt": "提取图片中的所有文字，不要加任何解释或格式：",
        "images": [base64_img],
        "stream": False,
        "keep_alive": "5m"
    }
    
    try:
        async with http_session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("response", "")
            else:
                return f"[API Error: {resp.status}]"
    except asyncio.TimeoutError:
        return "[Timeout: Ollama 响应超时]"
    except Exception as e:
        return f"[Connection Error: {str(e)}]"

# ================================
# WebSocket 流式引擎
# ================================
@app.websocket("/ws/ocr")
async def websocket_ocr(websocket: WebSocket):
    await websocket.accept()
    print("[WS] Client connected for streaming OCR")
    
    # 获取需要匹配的目标列表
    companies = load_json(TARGETS_FILE, [])
    config = load_json(CONFIG_FILE, {"matchThreshold": 0.6})
    threshold = config.get("matchThreshold", 0.6)
    
    try:
        while True:
            # 接收 Base64 或者 二进制 (这里演示接收文本Base64)
            data = await websocket.receive_text()
            
            # 兼容带有 data:image/jpeg;base64, 前缀的数据
            if "," in data:
                b64_str = data.split(",")[1]
            else:
                b64_str = data

            # 扔给大模型异步推理
            ocr_text = await call_ollama(b64_str)
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
        print("[WS] Client disconnected")
    except Exception as e:
        print(f"[WS] Error: {e}")
        try:
            await websocket.close()
        except: pass

# Serve Static files dynamically (to keep index.html on root)
@app.get("/")
async def root():
    return FileResponse("index.html")

@app.get("/{filename}")
async def get_static_file(filename: str):
    # === 安全: 防止路径穿越攻击 ===
    # 1. 禁止包含 .. 或 / 的路径
    if '..' in filename or '/' in filename or '\\' in filename:
        return JSONResponse({"error": "Invalid path"}, status_code=403)
    # 2. 只允许白名单扩展名
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": "File type not allowed"}, status_code=403)
    # 3. 确保文件在当前目录内
    filepath = os.path.join(os.getcwd(), filename)
    if not os.path.abspath(filepath).startswith(os.getcwd()):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    if os.path.exists(filepath) and os.path.isfile(filepath):
        return FileResponse(filepath)
    return JSONResponse({"error": "File not found"}, status_code=404)

if __name__ == "__main__":
    import uvicorn
    print("🚀 FastAPI Server starting on http://localhost:8080")
    uvicorn.run("server:app", host="0.0.0.0", port=8080, log_level="info")

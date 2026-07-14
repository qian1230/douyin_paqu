import sys
import asyncio
import subprocess
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

current_process = None
log_queue = asyncio.Queue()

# 全局保存用户选择的路径
user_selected_save_path = "downloads"

@app.post("/api/select-folder")

async def select_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        path = filedialog.askdirectory(title="选择视频保存文件夹")
        if path and os.path.isdir(path):
            return {"path": path.replace("\\", "/")}
        else:
            return {"path": ""}
    except:
        return {"path": ""}

@app.get("/", response_class=HTMLResponse)
async def root():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

class RecordingRequest(BaseModel):
    cookie: str | None = None
    category: str
    duration: int = 60
    max_recording: int = 6
    save_path: str = "downloads"

# ======================
# 启动录制（适配你的三层目录）
# ======================
@app.post("/api/start-recording")
async def start_recording(req: RecordingRequest):
    global current_process, user_selected_save_path

    if current_process and current_process.poll() is None:
        raise HTTPException(status_code=400, detail="正在运行")

    # ✅ 你的目录结构：三层上级目录
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script_path = os.path.join(root_dir, "record_category.py")

    # 保存用户选择的路径，给视频列表接口用
    user_selected_save_path = req.save_path

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [
        sys.executable, "-u", script_path,
        "--category", req.category,
        "--duration", str(req.duration),
        "--save-path", req.save_path,
        "--max-recording", str(req.max_recording),
    ]

    # 有cookie才传，不报错
    if req.cookie and req.cookie.strip():
        cmd.extend(["--cookie", req.cookie.strip()])

    current_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=root_dir,
        env=env,
        bufsize=0,
    )

    asyncio.create_task(read_logs())
    return {"status": "running"}
import json
@app.get("/api/total-duration")
async def get_total_duration(category: str):
    try:
        with open("record_stats.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        # 支持小数秒（54.187s → 转成整数）
        total = int(float(data.get(category, 0)))
    except:
        total = 0

    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60

    return {
        "total_seconds": total,
        "text": f"{h} 小时 {m} 分钟 {s} 秒"
    }
@app.post("/api/stop-recording")
async def stop_recording():
    global current_process
    if current_process and current_process.poll() is None:
        current_process.terminate()
        current_process.wait()
        current_process = None
    return {"status": "idle"}

@app.get("/api/status")
async def status():
    if current_process and current_process.poll() is None:
        return {"status": "running"}
    return {"status": "idle"}

# ======================
# ✅ 核心：实时视频列表（支持任意保存目录）
# ======================


# ======================
# 日志过滤（屏蔽ffmpeg刷屏错误）
# ======================
async def read_logs():
    while True:
        if not current_process or current_process.poll() is not None:
            await asyncio.sleep(0.2)
            continue

        try:
            line = current_process.stdout.readline()
            if line:
                txt = line.decode("utf-8", errors="replace").strip()
                blacklist = ["PPS", "decode_slice", "no frame!", "error(", "OpenCV", "cv::"]
                if txt and not any(bad in txt for bad in blacklist):
                    await log_queue.put(txt)
            await asyncio.sleep(0.05)
        except:
            await asyncio.sleep(0.1)

@app.websocket("/ws/logs")
async def ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            msg = await log_queue.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=6007)
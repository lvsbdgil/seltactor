"""Local, single-process prototype API. Start with: uvicorn backend.app:app --port 8000."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from datetime import date as Date
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from . import auth
from PIL import Image

from .pipeline import (
    DISCLAIMER, FRAMES_PER_VIDEO, MAX_IMAGES, MAX_PIXELS, MediaFile, PipelineError,
    analyze_images, prepare_media,
)

load_dotenv(Path(__file__).parent / ".env", override=False)
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-terra")
MAX_FILES = 12
MAX_FILE_BYTES = 2 * 1024 ** 3
MAX_TOTAL_BYTES = 4 * 1024 ** 3
MAX_PHOTO_BYTES = 50 * 1024 ** 2
MAX_PENDING = 8
MAX_SAVED_JOBS = 50
JOB_TTL = 3600
limits = {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES, "max_photo_bytes": MAX_PHOTO_BYTES,
          "max_total_bytes": MAX_TOTAL_BYTES, "max_images": MAX_IMAGES, "frames_per_video": FRAMES_PER_VIDEO}
app = FastAPI(title="SELTACTOR analysis API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
app.include_router(auth.router)


@app.middleware("http")
async def admin_boundary(request: Request, call_next):
    # Enforce before multipart parsing, including malformed/large guest uploads.
    try:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
            auth.check_origin(request)
        if request.method != "OPTIONS" and request.url.path.startswith("/api/analyses"):
            auth.require_admin(request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers={**(exc.headers or {}), "Cache-Control": "no-store"})
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


jobs: dict[str, dict] = {}
lock = threading.RLock()
workers = threading.Semaphore(2)


def configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def prune_jobs() -> None:
    now = time.time()
    with lock:
        finished = sorted((k for k, v in jobs.items() if v["status"] in {"completed", "failed"}),
                          key=lambda key: jobs[key]["created_at"])
        for key in finished:
            if now - jobs[key]["created_at"] > JOB_TTL or len(jobs) >= MAX_SAVED_JOBS:
                jobs.pop(key, None)


def public_job(job: dict) -> dict:
    return {key: value for key, value in job.items() if key != "created_at"}


@app.get("/api/health")
def health(request: Request):
    return {"status": "ok", "configured": configured(), "is_admin": auth.current_admin(request) is not None, "model": MODEL,
            "ffmpeg_available": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")), "limits": limits}


def run_job(job_id: str, directory: Path, media: list[MediaFile], field: str, crop: str, date: str) -> None:
    def progress(value: int, stage: str):
        with lock:
            jobs[job_id].update(status="processing", progress=value, stage=stage)
    try:
        with workers:
            progress(5, "Проверка и подготовка материалов")
            images = prepare_media(media, progress)
            progress(60, "OpenAI анализирует выборку изображений")
            report = analyze_images(images, field=field, crop=crop, date=date, model=MODEL)
            report["files_processed"] = len(media)
            with lock:
                jobs[job_id].update(status="completed", progress=100, stage="Отчёт готов", report=report)
    except PipelineError as exc:
        with lock:
            jobs[job_id].update(status="failed", stage="Не удалось завершить анализ", error=str(exc))
    except Exception:
        # Never send upstream exception objects, paths, stack traces or credentials to the browser.
        with lock:
            jobs[job_id].update(status="failed", stage="Ошибка обработки", error="Ошибка обработки материалов. Проверьте файлы и повторите анализ.")
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@app.post("/api/analyses", status_code=202)
async def create_analysis(background_tasks: BackgroundTasks, files: list[UploadFile] = File(...),
                          field: str = Form(..., max_length=200), crop: str = Form(..., max_length=100),
                          date: Date = Form(...)):
    directory: Path | None = None
    accepted = False
    try:
        if not configured():
            raise HTTPException(503, "OpenAI не настроен: добавьте OPENAI_API_KEY в backend/.env и перезапустите сервер.")
        if not field.strip() or not crop.strip():
            raise HTTPException(422, "Укажите поле и культуру.")
        if not 1 <= len(files) <= MAX_FILES:
            raise HTTPException(413, f"Добавьте от 1 до {MAX_FILES} файлов за одно обследование.")
        prune_jobs()
        with lock:
            if sum(j["status"] in {"queued", "processing"} for j in jobs.values()) >= MAX_PENDING:
                raise HTTPException(429, "Очередь анализа заполнена. Дождитесь завершения текущих обследований.")
        directory = Path(tempfile.mkdtemp(prefix="seltactor-analysis-"))
        media: list[MediaFile] = []
        total = 0
        for upload in files:
            # Generated disk name prevents traversal; original filename is only display metadata.
            name = Path((upload.filename or "material").replace("\\", "/")).name[:180]
            extension = Path(name).suffix.lower()
            video = extension in {".mp4", ".mov"}
            if extension not in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}:
                raise HTTPException(415, "Поддерживаются JPEG, PNG, WebP, MP4 и MOV.")
            target = directory / f"{uuid4().hex}{extension}"
            size = 0
            byte_limit = MAX_FILE_BYTES if video else MAX_PHOTO_BYTES
            with target.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    total += len(chunk)
                    if size > byte_limit or total > MAX_TOTAL_BYTES:
                        raise HTTPException(413, "Превышен лимит: фото до 50 МБ, видео до 2 ГБ, весь набор до 4 ГБ.")
                    output.write(chunk)
            if size == 0:
                raise HTTPException(422, "Один из файлов пуст.")
            if not video:
                try:
                    with Image.open(target) as image:
                        if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > MAX_PIXELS:
                            raise ValueError("unsupported image")
                        image.verify()
                except Exception:
                    raise HTTPException(415, "Содержимое фотографии повреждено или не соответствует поддерживаемому изображению.") from None
            media.append(MediaFile(target, name, video))
        job_id = uuid4().hex
        job = {"id": job_id, "status": "queued", "progress": 0, "stage": "Материалы приняты",
               "report": None, "error": None, "created_at": time.time()}
        with lock:
            # Recheck after streaming: parallel clients may have filled the queue during upload.
            if sum(j["status"] in {"queued", "processing"} for j in jobs.values()) >= MAX_PENDING:
                raise HTTPException(429, "Очередь анализа заполнена. Повторите позже.")
            jobs[job_id] = job
        background_tasks.add_task(run_job, job_id, directory, media, field.strip(), crop.strip(), date.isoformat())
        accepted = True
        return public_job(job)
    finally:
        for upload in files:
            await upload.close()
        if directory is not None and not accepted:
            shutil.rmtree(directory, ignore_errors=True)


@app.get("/api/analyses/{job_id}")
def get_analysis(job_id: str):
    prune_jobs()
    with lock:
        if job_id not in jobs:
            raise HTTPException(404, "Обследование не найдено или срок хранения истёк. Загрузите материалы повторно.")
        return public_job(jobs[job_id])

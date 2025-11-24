import os
import tempfile
import subprocess
import mimetypes
import shutil
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


def _detect_extension(upload: UploadFile) -> str:
    # из имени файла
    ext = Path(upload.filename or "").suffix.lower()
    if ext:
        return ext

    # из content_type
    if upload.content_type:
        guessed = mimetypes.guess_extension(upload.content_type)
        if guessed:
            return guessed

    return ".mp4"


def _is_video(upload: UploadFile) -> bool:
    if upload.content_type and upload.content_type.startswith("video/"):
        return True

    ext = Path(upload.filename or "").suffix.lower()
    if ext:
        guessed, _ = mimetypes.guess_type("dummy" + ext)
        if guessed and guessed.startswith("video/"):
            return True

    return False


@app.post("/api/add-emoji")
async def add_emoji(file: UploadFile = File(...)):
    if not _is_video(file):
        raise HTTPException(status_code=400, detail="Only video files are allowed")

    ext = _detect_extension(file)
    media_type = file.content_type or "video/mp4"

    # создаём временную директорию, НО теперь сами её удалим позже
    tmpdir = tempfile.mkdtemp()
    input_path = os.path.join(tmpdir, f"input{ext}")
    output_path = os.path.join(tmpdir, f"output{ext}")

    # сохраняем входной файл
    with open(input_path, "wb") as f:
        f.write(await file.read())

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        (
            "drawtext=text='😀':"
            "fontsize=72:"
            "x=(w-text_w)/2:y=(h-text_h)/2:"
            "fontcolor=white"
        ),
        "-codec:a",
        "copy",
        output_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        print("FFMPEG ERROR:", e.stderr.decode(errors="ignore"))
        # подчистим директорию, если ffmpeg упал
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="ffmpeg processing error")

    if not os.path.exists(output_path):
        # на всякий случай — если ffmpeg не создал файл
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="output file was not created")

    # фоновая задача удалит временную папку, когда ответ будет отправлен
    background = BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True)

    return FileResponse(
        output_path,
        media_type=media_type,
        filename=f"output{ext}",
        background=background,
    )

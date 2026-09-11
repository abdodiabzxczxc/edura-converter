"""
Edura PPTX Converter — Professional v2
Fast PPTX→PNG conversion using LibreOffice with:
- max_slides support (convert only needed slides)
- Lower resolution for fast preview
- Proper error handling + timeouts
"""

import os
import re
import uuid
import glob
import base64
import shutil
import subprocess
import tempfile
import io
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image

app = FastAPI(title="Edura Converter", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
PREVIEW_WIDTH = 1280  # px — fast enough, good quality
LO_TIMEOUT = 90  # seconds per conversion


def img_to_b64(img: Image.Image, width: int = PREVIEW_WIDTH) -> tuple[str, int, int]:
    """Resize and encode image to base64 PNG."""
    if img.width > width:
        ratio = width / img.width
        img = img.resize((width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, compress_level=6)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}", img.width, img.height


def sort_key(path: str) -> int:
    """Sort slide PNGs: presentation.png=0, presentation2.png=2, etc."""
    stem = Path(path).stem  # e.g. "presentation", "presentation2"
    nums = re.findall(r"\d+", stem)
    return int(nums[-1]) if nums else 0


@app.get("/")
@app.get("/health")
def health():
    return {"status": "ok", "service": "Edura Converter", "version": "2.0"}


@app.post("/convert/pptx")
async def convert_pptx(
    file: UploadFile = File(...),
    max_slides: Optional[int] = Form(None),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large (max 100MB)")

    work_dir = tempfile.mkdtemp(prefix="edura_")
    try:
        # Save file
        safe_name = "presentation.pptx"
        input_path = os.path.join(work_dir, safe_name)
        with open(input_path, "wb") as f:
            f.write(content)

        # Run LibreOffice: PPTX → PNG (one file per slide)
        env = {**os.environ, "HOME": work_dir, "TMPDIR": work_dir}
        result = subprocess.run(
            [
                "libreoffice", "--headless", "--norestore",
                "--convert-to", "png",
                "--outdir", work_dir,
                input_path,
            ],
            capture_output=True,
            text=True,
            timeout=LO_TIMEOUT,
            env=env,
        )

        # Find generated PNGs
        all_pngs = sorted(
            glob.glob(os.path.join(work_dir, "presentation*.png")),
            key=sort_key,
        )

        if not all_pngs:
            raise HTTPException(422, f"LibreOffice produced no output. stderr: {result.stderr[:500]}")

        # Apply max_slides limit
        if max_slides and max_slides > 0:
            all_pngs = all_pngs[:max_slides]

        # Encode each PNG
        slides = []
        for i, png_path in enumerate(all_pngs):
            img = Image.open(png_path).convert("RGB")
            b64, w, h = img_to_b64(img)
            slides.append({"index": i, "width": w, "height": h, "image": b64})

        return JSONResponse({
            "success": True,
            "slideCount": len(slides),
            "totalSlides": len(glob.glob(os.path.join(work_dir, "presentation*.png"))),
            "slides": slides,
        })

    except subprocess.TimeoutExpired:
        raise HTTPException(504, "LibreOffice timed out — file may be too large or complex")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.post("/convert/pptx/range")
async def convert_pptx_range(
    file: UploadFile = File(...),
    start: int = Form(0),
    end: int = Form(10),
):
    """Convert a specific range of slides."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large")

    work_dir = tempfile.mkdtemp(prefix="edura_range_")
    try:
        input_path = os.path.join(work_dir, "presentation.pptx")
        with open(input_path, "wb") as f:
            f.write(content)

        env = {**os.environ, "HOME": work_dir, "TMPDIR": work_dir}
        subprocess.run(
            ["libreoffice", "--headless", "--norestore",
             "--convert-to", "png", "--outdir", work_dir, input_path],
            capture_output=True, timeout=LO_TIMEOUT, env=env,
        )

        all_pngs = sorted(
            glob.glob(os.path.join(work_dir, "presentation*.png")),
            key=sort_key,
        )
        requested = all_pngs[start:end]

        slides = []
        for i, png_path in enumerate(requested):
            img = Image.open(png_path).convert("RGB")
            b64, w, h = img_to_b64(img)
            slides.append({"index": start + i, "width": w, "height": h, "image": b64})

        return JSONResponse({
            "success": True,
            "slideCount": len(slides),
            "totalSlides": len(all_pngs),
            "slides": slides,
        })
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

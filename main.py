"""
Edura PPTX Converter Service
Converts PPTX slides → high-quality PNG images using LibreOffice
Deploy on Render.com as a Docker service
"""

import os
import uuid
import glob
import base64
import shutil
import subprocess
import tempfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="Edura Converter", version="1.0.0")

# Allow all origins (your Next.js frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/pdf",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@app.get("/")
def health():
    return {"status": "ok", "service": "Edura Converter"}


@app.get("/health")
def ping():
    return {"status": "healthy"}


@app.post("/convert/pptx")
async def convert_pptx(file: UploadFile = File(...)):
    """
    Convert a PPTX file to PNG images (one per slide).
    Returns: { slides: [{ index, width, height, image: "data:image/png;base64,..." }] }
    """
    # Read file
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50MB)")

    work_dir = tempfile.mkdtemp(prefix="edura_")
    try:
        # Save uploaded file
        input_path = os.path.join(work_dir, "presentation.pptx")
        with open(input_path, "wb") as f:
            f.write(content)

        # Step 1: Convert PPTX → PNG using LibreOffice
        # LibreOffice generates one PNG per slide named: presentation.png, presentation2.png, ...
        result = subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to", "png",
                "--outdir", work_dir,
                input_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "HOME": work_dir},
        )

        if result.returncode != 0:
            # Fallback: try with export filter
            result = subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--infilter=Impress MS PowerPoint 2007 XML",
                    "--convert-to", "png",
                    "--outdir", work_dir,
                    input_path,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "HOME": work_dir},
            )

        # Find all generated PNGs
        png_files = sorted(
            glob.glob(os.path.join(work_dir, "*.png")),
            key=lambda p: (
                0 if p.endswith("presentation.png") else
                int("".join(filter(str.isdigit, Path(p).stem.replace("presentation", "") or "1")) or "1")
            ),
        )

        if not png_files:
            raise HTTPException(
                status_code=422,
                detail="Could not convert file. Make sure it's a valid PPTX."
            )

        # Read PNGs and encode as base64
        slides = []
        for i, png_path in enumerate(png_files):
            with open(png_path, "rb") as f:
                png_bytes = f.read()

            # Get dimensions using Pillow
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(png_bytes))
            width, height = img.size

            # Resize if too large (cap at 1920px wide for performance)
            if width > 1920:
                ratio = 1920 / width
                new_size = (1920, int(height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                png_bytes = buf.getvalue()
                width, height = new_size

            b64 = base64.b64encode(png_bytes).decode("utf-8")
            slides.append({
                "index": i,
                "width": width,
                "height": height,
                "image": f"data:image/png;base64,{b64}",
            })

        return JSONResponse({
            "success": True,
            "slideCount": len(slides),
            "slides": slides,
        })

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Conversion timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.post("/convert/docx")
async def convert_docx(file: UploadFile = File(...)):
    """
    Convert DOCX → HTML using LibreOffice (for better preview).
    Returns: { html: "..." }
    """
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    work_dir = tempfile.mkdtemp(prefix="edura_docx_")
    try:
        input_path = os.path.join(work_dir, "document.docx")
        with open(input_path, "wb") as f:
            f.write(content)

        result = subprocess.run(
            [
                "libreoffice", "--headless",
                "--convert-to", "html",
                "--outdir", work_dir,
                input_path,
            ],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HOME": work_dir},
        )

        html_files = glob.glob(os.path.join(work_dir, "*.html"))
        if not html_files:
            raise HTTPException(status_code=422, detail="Could not convert DOCX")

        with open(html_files[0], "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()

        return JSONResponse({"success": True, "html": html})

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

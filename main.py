"""
Edura PPTX Converter v3 — Professional
Fast 2-step conversion: PPTX→PDF (fast) then PDF→PNG (selective pages)
Much faster and lower memory than PPTX→PNG directly
"""

import os, re, uuid, glob, base64, shutil, subprocess, tempfile, io
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image

app = FastAPI(title="Edura Converter", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_MB = 80
PREVIEW_WIDTH = 1280


def img_to_b64(img: Image.Image, width: int = PREVIEW_WIDTH) -> tuple[str, int, int]:
    if img.width > width:
        r = width / img.width
        img = img.resize((width, int(img.height * r)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, compress_level=7)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}", img.width, img.height


@app.get("/")
@app.get("/health")
def health():
    return {"status": "ok", "service": "Edura Converter", "version": "3.0"}


@app.post("/convert/pptx")
async def convert_pptx(
    file: UploadFile = File(...),
    max_slides: Optional[int] = Form(10),
):
    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_FILE_MB}MB)")

    n = min(int(max_slides or 10), 20)  # cap at 20 slides max
    work_dir = tempfile.mkdtemp(prefix="edura_")

    try:
        # ── Step 1: PPTX → PDF (fast, low memory) ──
        pptx_path = os.path.join(work_dir, "presentation.pptx")
        with open(pptx_path, "wb") as f:
            f.write(content)

        env = {**os.environ, "HOME": work_dir, "TMPDIR": work_dir}

        r1 = subprocess.run(
            ["libreoffice", "--headless", "--norestore",
             "--convert-to", "pdf", "--outdir", work_dir, pptx_path],
            capture_output=True, text=True, timeout=60, env=env,
        )

        pdf_path = os.path.join(work_dir, "presentation.pdf")
        if not os.path.exists(pdf_path):
            raise HTTPException(422, f"PDF conversion failed: {r1.stderr[:300]}")

        # ── Step 2: PDF pages → PNG (selective, very fast) ──
        # pdftoppm converts specific pages only
        out_prefix = os.path.join(work_dir, "slide")
        r2 = subprocess.run(
            ["pdftoppm", "-f", "1", "-l", str(n),
             "-r", "120",       # 120 DPI — good quality, fast
             "-png", pdf_path, out_prefix],
            capture_output=True, timeout=30, env=env,
        )

        pngs = sorted(glob.glob(os.path.join(work_dir, "slide-*.png")))
        if not pngs:
            # fallback: use direct LibreOffice PNG if pdftoppm failed
            pngs = sorted(glob.glob(os.path.join(work_dir, "presentation*.png")))

        if not pngs:
            raise HTTPException(422, "No output images generated")

        slides = []
        for i, p in enumerate(pngs[:n]):
            img = Image.open(p).convert("RGB")
            b64, w, h = img_to_b64(img)
            slides.append({"index": i, "width": w, "height": h, "image": b64})

        return JSONResponse({
            "success": True,
            "slideCount": len(slides),
            "slides": slides,
        })

    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Conversion timed out — file may be too complex")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

"""
Edura PPTX Converter v4 — Production Engine
Full Arabic font support + isolated user profile + robust PDF fallback
"""

import os, re, uuid, glob, base64, shutil, subprocess, tempfile, io
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image

app = FastAPI(title="Edura Converter", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_MB = 100
PREVIEW_WIDTH = 1280


def img_to_b64(img: Image.Image, width: int = PREVIEW_WIDTH) -> tuple[str, int, int]:
    if img.width > width:
        r = width / img.width
        img = img.resize((width, int(img.height * r)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, compress_level=6)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}", img.width, img.height


@app.get("/")
@app.get("/health")
def health():
    return {"status": "ok", "service": "Edura Converter", "version": "4.0"}


@app.post("/convert/pptx")
async def convert_pptx(
    file: UploadFile = File(...),
    max_slides: Optional[int] = Form(20),
):
    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_FILE_MB}MB)")

    n = min(int(max_slides or 20), 50)
    work_dir = tempfile.mkdtemp(prefix="edura_v4_")

    try:
        pptx_path = os.path.join(work_dir, "input.pptx")
        with open(pptx_path, "wb") as f:
            f.write(content)

        user_profile = os.path.join(work_dir, "profile")
        os.makedirs(user_profile, exist_ok=True)

        env = {
            **os.environ,
            "HOME": work_dir,
            "TMPDIR": work_dir,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }

        # ── Step 1: Run LibreOffice with isolated profile ──
        cmd = [
            "libreoffice",
            f"-env:UserInstallation=file://{user_profile}",
            "--headless",
            "--invisible",
            "--nodefault",
            "--nofirststartwizard",
            "--nolockcheck",
            "--nologo",
            "--norestore",
            "--convert-to", "pdf:impress_pdf_Export",
            "--outdir", work_dir,
            pptx_path,
        ]

        r1 = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)

        # Check for any generated PDF
        pdfs = glob.glob(os.path.join(work_dir, "*.pdf"))
        if not pdfs:
            # Fallback without explicit filter name
            cmd_fallback = [
                "libreoffice",
                f"-env:UserInstallation=file://{user_profile}",
                "--headless",
                "--norestore",
                "--convert-to", "pdf",
                "--outdir", work_dir,
                pptx_path,
            ]
            r1 = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=120, env=env)
            pdfs = glob.glob(os.path.join(work_dir, "*.pdf"))

        if not pdfs:
            raise HTTPException(422, f"Conversion failed: stdout={r1.stdout[:150]}, stderr={r1.stderr[:150]}")

        pdf_path = pdfs[0]

        # ── Step 2: Convert PDF pages to PNG using pdftoppm ──
        out_prefix = os.path.join(work_dir, "slide")
        subprocess.run(
            ["pdftoppm", "-f", "1", "-l", str(n),
             "-r", "130",
             "-png", pdf_path, out_prefix],
            capture_output=True, timeout=60, env=env,
        )

        pngs = sorted(glob.glob(os.path.join(work_dir, "slide-*.png")))
        if not pngs:
            raise HTTPException(422, "No slide images could be extracted from PDF")

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
        raise HTTPException(504, "Conversion timed out on large file")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

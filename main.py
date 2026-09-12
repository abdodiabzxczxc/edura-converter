"""
Edura PPTX Converter & Document Engine v5 — Production Engine
Full Arabic font support + isolated user profile + ONLYOFFICE Document Hosting & Callback API
"""

import os, re, uuid, glob, base64, shutil, subprocess, tempfile, io, json, urllib.request
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from PIL import Image

app = FastAPI(title="Edura Converter & Document Engine", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_MB = 100
PREVIEW_WIDTH = 1280
STORAGE_DIR = Path("/tmp/edura_storage")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


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
    return {"status": "ok", "service": "Edura Document & Converter Engine", "version": "5.0"}


# ── ONLYOFFICE File Hosting & Management Endpoints ──────────────────────────

@app.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
):
    """Uploads a document file and returns a public direct download URL for ONLYOFFICE"""
    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_FILE_MB}MB)")

    raw_ext = Path(file.filename or "file.pptx").suffix
    ext = raw_ext if raw_ext else ".pptx"
    file_id = str(uuid.uuid4())
    stored_name = f"{file_id}{ext}"
    dest_path = STORAGE_DIR / stored_name

    with open(dest_path, "wb") as f:
        f.write(content)

    meta = {
        "file_id": file_id,
        "original_name": file.filename or stored_name,
        "size": len(content),
        "extension": ext,
    }
    with open(STORAGE_DIR / f"{file_id}.json", "w") as f:
        json.dump(meta, f)

    host = "https://edura-converter-production.up.railway.app"
    download_url = f"{host}/files/download/{stored_name}"

    return {
        "success": True,
        "file_id": file_id,
        "filename": file.filename or stored_name,
        "size": len(content),
        "url": download_url,
    }


@app.get("/files/download/{filename}")
async def download_file(filename: str):
    """Public direct download endpoint for ONLYOFFICE Document Server and users"""
    clean_name = os.path.basename(filename)
    file_path = STORAGE_DIR / clean_name

    if not file_path.exists():
        raise HTTPException(404, "File not found or expired")

    ext = Path(clean_name).suffix.lower()
    media_types = {
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=file_path,
        filename=clean_name,
        media_type=media_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.post("/files/callback/{file_id}")
async def onlyoffice_callback(file_id: str, request: Request):
    """Webhook called by ONLYOFFICE Document Server when document is edited or saved."""
    try:
        body = await request.json()
        status = body.get("status")
        download_url = body.get("url")

        if status in [2, 6] and download_url:
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "EduraDocumentServer/5.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()

            matching = list(STORAGE_DIR.glob(f"{file_id}.*"))
            save_path = matching[0] if matching else (STORAGE_DIR / f"{file_id}.pptx")
            with open(save_path, "wb") as f:
                f.write(data)

            meta_path = STORAGE_DIR / f"{file_id}.json"
            if meta_path.exists():
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                meta["updated"] = True
                meta["updated_size"] = len(data)
                with open(meta_path, "w") as f:
                    json.dump(meta, f)

        return {"error": 0}
    except Exception as e:
        print(f"Callback error for {file_id}: {e}")
        return {"error": 0}


@app.get("/files/status/{file_id}")
async def file_status(file_id: str):
    """Returns the current status of a stored file"""
    matching = [p for p in STORAGE_DIR.glob(f"{file_id}.*") if not p.name.endswith(".json")]
    if not matching:
        raise HTTPException(404, "File not found")
    f = matching[0]
    return {
        "file_id": file_id,
        "filename": f.name,
        "size": f.stat().st_size,
        "download_url": f"https://edura-converter-production.up.railway.app/files/download/{f.name}",
    }


# ── Legacy Converter Endpoint (Fallback) ────────────────────────────────────

@app.post("/convert/pptx")
async def convert_pptx(
    file: UploadFile = File(...),
    max_slides: Optional[int] = Form(20),
):
    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_FILE_MB}MB)")

    n = min(int(max_slides or 20), 50)
    work_dir = tempfile.mkdtemp(prefix="edura_v5_")

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

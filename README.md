# Edura Converter Service

Python FastAPI service that converts PPTX/DOCX files to images using LibreOffice.
Deploy on Render.com as a **Docker** service.

## Deploy to Render

1. Push this folder to a GitHub repo
2. Go to render.com → New → Web Service
3. Connect your GitHub repo
4. Select **Docker** as runtime
5. Set these settings:
   - **Name:** edura-converter
   - **Region:** Choose closest to you
   - **Plan:** Free (or Starter for production)
6. Click **Create Web Service**
7. Wait ~5 minutes for build (LibreOffice is large)
8. Copy your service URL (e.g. `https://edura-converter.onrender.com`)

## API Endpoints

### `POST /convert/pptx`
Upload a PPTX file, get back PNG images for each slide.

**Request:** multipart/form-data with `file` field

**Response:**
```json
{
  "success": true,
  "slideCount": 5,
  "slides": [
    {
      "index": 0,
      "width": 1920,
      "height": 1080,
      "image": "data:image/png;base64,..."
    }
  ]
}
```

### `GET /health`
Health check endpoint.

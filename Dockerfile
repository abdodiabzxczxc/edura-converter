FROM python:3.11-slim

# Install LibreOffice + poppler-utils (pdftoppm) — the 2-step conversion stack
RUN apt-get update && apt-get install -y \
    libreoffice \
    libreoffice-impress \
    poppler-utils \
    fonts-liberation \
    fonts-dejavu \
    fontconfig \
    --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000", "--timeout-keep-alive", "120"]

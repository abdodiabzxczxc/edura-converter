FROM python:3.11-slim

# Install LibreOffice, JRE, poppler, and complete Arabic & Latin fonts
RUN apt-get update && apt-get install -y \
    libreoffice \
    libreoffice-impress \
    libreoffice-common \
    default-jre-headless \
    poppler-utils \
    fonts-liberation \
    fonts-dejavu \
    fonts-noto-core \
    fonts-amiri \
    fonts-kacst \
    fonts-sil-scheherazade \
    fontconfig \
    --no-install-recommends \
    && fc-cache -f \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000", "--timeout-keep-alive", "120"]

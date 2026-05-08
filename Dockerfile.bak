FROM python:3.11-slim

# ── 시스템 패키지 설치 ─────────────────────────────────────
# poppler-utils: pdftotext (PDF → MD/JSON)
# nodejs + npm: docx 라이브러리로 교안 DOCX 생성
# tesseract: OCR 백업용
# fonts-nanum: 한글 폰트 (PDF 리포트 생성)
RUN apt-get update && apt-get install -y \
    poppler-utils \
    nodejs \
    npm \
    tesseract-ocr \
    tesseract-ocr-kor \
    libgl1-mesa-glx \
    libglib2.0-0 \
    fonts-nanum \
    fonts-nanum-coding \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python 의존성 (캐시 활용) ──────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Node.js 의존성 ────────────────────────────────────────
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ── 앱 코드 복사 ──────────────────────────────────────────
COPY . .

# ── 데이터 디렉토리 ───────────────────────────────────────
RUN mkdir -p /app/data/uploads /app/data/outputs /app/data/lesson_json /app/data/chroma_db

# ── 헬스체크 ──────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "main.py"]

"""
kihobot_x 공통 설정
===================
환경변수 · 경로 · 로깅 · 상수
"""
import os
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── 경로 ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
LESSON_JSON_DIR = DATA_DIR / "lesson_json"
CHROMA_DIR = DATA_DIR / "chroma_db"

for d in [DATA_DIR, UPLOAD_DIR, OUTPUT_DIR, LESSON_JSON_DIR, CHROMA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── 환경변수 ───────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:12b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

POPPLER_PATH = os.getenv("POPPLER_PATH", "")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DATA_DIR}/kihobot.db"
)

# Cloudflare Tunnel
CLOUDFLARE_TUNNEL_TOKEN = os.getenv("CLOUDFLARE_TUNNEL_TOKEN", "")

# ─── 로깅 ───────────────────────────────────────────────
def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

logger = logging.getLogger("kihobot")


def log_startup_info():
    logger.info(f"BASE_DIR: {BASE_DIR}")
    logger.info(f"DATABASE_URL: {DATABASE_URL}")
    logger.info(f"GEMINI_API_KEY: {'✓ 설정됨' if GEMINI_API_KEY else '✗ 미설정'}")
    logger.info(f"POPPLER_PATH: {POPPLER_PATH or '(Docker는 apt-get 사용)'}")

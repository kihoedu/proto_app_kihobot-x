#!/usr/bin/env python3
"""
kihobot_x - 통합 진입점
=======================
박기호논술 통합 플랫폼
 · portal       : / (메인 홈)
 · eval_engine  : /eval (평가엔진 · 논술 첨삭)
 · analy_engine : /analy (분석엔진 · 교안 · PPT)
"""
import sys
import uvicorn
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 프로젝트 루트를 sys.path 에 추가 (모듈 import 용)
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from common.config import setup_logging, log_startup_info
from common.database import init_db

# ── 로깅 세팅 ────────────────────────────────────────────
setup_logging()
log_startup_info()

# ── FastAPI 앱 생성 ─────────────────────────────────────
app = FastAPI(
    title="kihobot_x",
    version="1.0.0",
    description="박기호논술 통합 플랫폼 - 분석엔진(교안) + 평가엔진(첨삭)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 라우터 등록 ─────────────────────────────────────────
from portal.routes import router as portal_router
from eval_engine.routes import router as eval_router
from analy_engine.routes import router as analy_router

app.include_router(portal_router, tags=["portal"])
app.include_router(eval_router, prefix="/eval", tags=["eval_engine"])
app.include_router(analy_router, prefix="/analy", tags=["analy_engine"])


# ── 정적 파일 ───────────────────────────────────────────
static_dir = BASE / "common" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── 시작 훅 ─────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    from eval_engine.models import init_db
    from eval_engine.services.crud import init_default_system_prompt
    init_db()
    init_default_system_prompt()
    print("\n" + "=" * 60)
    print("  🤖 kihobot_x 통합 플랫폼 기동")
    print("=" * 60)
    print("  포털 홈:   http://localhost:8000/")
    print("  평가엔진:  http://localhost:8000/eval/")
    print("  분석엔진:  http://localhost:8000/analy/")
    print("=" * 60 + "\n")


# ── 실행 ────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    is_prod = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("KIHOBOT_ENV") == "production"

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=not is_prod,
    )

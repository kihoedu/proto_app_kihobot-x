"""
포털 홈 라우트
==============
/ 메인 대시보드 · 두 엔진으로 진입.
"""
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE / "common" / "templates"))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def portal_home(request: Request):
    """메인 포털 - 두 개의 큰 버튼"""
    return templates.TemplateResponse(
        request=request,
        name="portal.html",
        context={"active_page": "home"},
    )


@router.get("/health")
def health():
    """전체 시스템 상태 확인"""
    import os
    checks = {
        "status": "ok",
        "gemini_api": "✓" if os.getenv("GEMINI_API_KEY") else "✗",
    }
    return checks

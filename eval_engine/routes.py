#!/usr/bin/env python3
"""
평가엔진 라우트 - 논술 답안 OCR + 멀티에이전트 첨삭 + PDF 리포트

main.py 에서 /eval prefix 로 include:
  app.include_router(eval_router, prefix="/eval", tags=["eval_engine"])

프런트(eval_engine/templates/index.html) 가 호출하는 모든 엔드포인트:
  GET  /                              → SPA 메인
  POST /api/batch-analyze              → 업로드된 PDF/이미지 헤더 자동 분석
  POST /api/batch-submit               → 여러 학생 일괄 제출
  POST /api/submit                     → 단일 학생 제출 (수동 모드)
  GET  /api/status/{submission_id}
  GET  /api/report/{submission_id}
  GET  /api/report/{submission_id}/pdf
  POST /api/item/{item_id}/ocr         → OCR 교사 수정본 저장
  POST /api/item/{item_id}/annotate    → 문항별 첨삭 트리거
  POST /api/item/{item_id}/review      → 교사 검토 결과 저장
  GET  /api/reports                    → 평가 목록
  DELETE /api/reports/{submission_id}
  GET/POST /api/students
  DELETE /api/students/{student_id}
  GET/POST /api/problems
  GET/DELETE /api/problems/{problem_id}
  GET/POST /api/groups
  GET/DELETE /api/groups/{group_id}
  GET/POST /api/system-prompts
  GET/DELETE /api/system-prompts/{prompt_id}
  GET/POST /api/settings
"""
import os
import shutil
import uuid
import json
import logging
import tempfile
import traceback
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import (
    APIRouter, UploadFile, File, Form, HTTPException,
    BackgroundTasks, Request, Body,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from eval_engine.models import init_db, SessionLocal, SubmissionItemORM
from eval_engine.services.pipeline import run_ocr_only, run_annotation
from eval_engine.services.batch_processor import process_uploaded_files
from eval_engine.services.pdf_generator import generate_pdf
from eval_engine.services.crud import (
    # 시스템 프롬프트
    init_default_system_prompt,
    upsert_system_prompt, get_system_prompt,
    get_default_system_prompt, list_system_prompts,
    # 문제
    create_or_update_problem, get_problem, list_problems, delete_problem,
    # 학생
    upsert_student, get_student, list_students, delete_student,
    # 제출
    create_submission, get_submission, get_submission_status,
    update_submission_status, list_submissions, delete_submission,
    save_teacher_item_result, update_item_ocr_text,
    # 그룹
    create_or_update_group, get_group, list_groups, delete_group,
    get_group_with_problems,
    # 통계 / 설정
    get_statistics,
    get_setting, set_setting, get_all_settings,
    get_llm_provider, get_ollama_model, get_gemini_model,
)

logger = logging.getLogger("kihobot.eval")

# ─── 경로 / 디렉토리 ─────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
_is_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None
_default_upload = "/tmp/uploads" if _is_railway else str(BASE / "data" / "uploads")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", _default_upload))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

REPORT_DIR = BASE / "data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ─── APIRouter ───────────────────────────────────────────────
router = APIRouter()
templates = Jinja2Templates(directory=str(BASE / "eval_engine" / "templates"))


def init_eval_engine():
    """main.py on_startup 에서 호출"""
    init_db()
    init_default_system_prompt()


# ═══════════════════════════════════════════════════════════════
# 메인 페이지
# ═══════════════════════════════════════════════════════════════
@router.get("/", response_class=HTMLResponse)
def eval_index(request: Request):
    """평가엔진 SPA 메인"""
    return templates.TemplateResponse(request=request, name="index.html")


# ═══════════════════════════════════════════════════════════════
# 1. 업로드 & 헤더 자동 분석
# ═══════════════════════════════════════════════════════════════
@router.post("/api/batch-analyze")
async def batch_analyze(files: list[UploadFile] = File(...)):
    """
    업로드된 이미지/PDF 파일들의 헤더를 자동 분석.
    반환: {grouped, page_infos, total_pages, total_students}
    프런트에서 이 결과를 편집한 뒤 /api/batch-submit 로 재전송.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(500, "GEMINI_API_KEY 환경변수가 없습니다.")

    # 임시 디렉토리에 업로드 파일 저장
    tmp_dir = tempfile.mkdtemp(prefix="eval_batch_", dir=str(UPLOAD_DIR))
    saved_paths = []
    try:
        for f in files:
            dest = Path(tmp_dir) / f.filename
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out)
            saved_paths.append(str(dest))

        result = process_uploaded_files(saved_paths, api_key, tmp_dir)

        # filename 필드를 grouped 에 없는 경우를 위해 page_infos 에도 유지
        for info in result.get("page_infos", []):
            if "filename" not in info and info.get("image_path"):
                info["filename"] = Path(info["image_path"]).name

        return JSONResponse(result)
    except Exception as e:
        logger.error(f"batch-analyze 실패: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(500, f"헤더 분석 실패: {str(e)}")


# ═══════════════════════════════════════════════════════════════
# 2. 일괄 제출
# ═══════════════════════════════════════════════════════════════
@router.post("/api/batch-submit")
async def batch_submit(
    background_tasks: BackgroundTasks,
    payload: dict = Body(...),
):
    """
    여러 학생 일괄 제출.
    payload = {grouped: {학생명: {group_id, academy_name, items: {번호: {problem_id, image_paths, problem_type}}}}, ...}
    각 학생별 submission 생성 + OCR 백그라운드 실행.
    반환: {submission_ids: [{submission_id, student_name}, ...]}
    """
    grouped = payload.get("grouped", {})
    submission_ids = []

    for student_name, s_info in grouped.items():
        if student_name == "미확인" or not student_name:
            continue

        student_id = student_name  # 이름을 그대로 ID로 사용 (프런트와 일관)
        academy_name = s_info.get("academy_name", "")
        submit_date = s_info.get("submit_date", "")
        group_id = s_info.get("group_id", "")
        items = s_info.get("items", {})

        # 문항 리스트 구성 (unassigned 제외)
        item_groups = []
        for num_key, item_info in items.items():
            if num_key == "unassigned":
                continue
            try:
                num = int(num_key)
            except (ValueError, TypeError):
                continue
            image_paths = item_info.get("image_paths", [])
            if not image_paths:
                continue
            item_groups.append({
                "item_number": num,
                "image_paths": image_paths,
                "problem_id": item_info.get("problem_id") or None,
                "problem_type": item_info.get("problem_type", ""),
            })

        if not item_groups:
            continue

        # 학생 + 제출 생성
        submission_id = uuid.uuid4().hex[:12]
        upsert_student(student_id, name=student_name)
        create_submission(
            submission_id=submission_id,
            student_id=student_id,
            problem_id=None,  # 그룹 내 여러 문항이라 submission 레벨 problem_id 는 null
            item_groups=item_groups,
            academy_name=academy_name,
            submit_date=submit_date,
        )

        # group_id 저장 (추가 메타 — submission 레벨)
        # (models.py 에 group_id 필드가 없을 수 있으므로 academy_name 등만 사용)

        # OCR 백그라운드 실행용 item_groups 재구성 (item_id 포함 필요)
        db = SessionLocal()
        try:
            item_rows = db.query(SubmissionItemORM).filter_by(
                submission_id=submission_id
            ).all()
            ocr_groups = []
            for row in item_rows:
                ocr_groups.append({
                    "item_id": row.item_id,
                    "item_number": row.item_number,
                    "image_paths": row.image_paths or [],
                    "problem_id": row.problem_id,
                })
        finally:
            db.close()

        background_tasks.add_task(_run_ocr_safe, submission_id, ocr_groups)
        submission_ids.append({
            "submission_id": submission_id,
            "student_name": student_name,
        })

    return JSONResponse({"submission_ids": submission_ids})


def _run_ocr_safe(submission_id: str, item_groups: list[dict]):
    """백그라운드에서 OCR 실행 (예외 안전)"""
    try:
        run_ocr_only(submission_id, item_groups)
    except Exception as e:
        logger.error(f"OCR 실패 [{submission_id}]: {e}")
        logger.error(traceback.format_exc())
        update_submission_status(submission_id, "error", str(e))


# ═══════════════════════════════════════════════════════════════
# 3. 단일 제출 (수동 모드 폴백)
# ═══════════════════════════════════════════════════════════════
@router.post("/api/submit")
async def submit_single(
    background_tasks: BackgroundTasks,
    student_id: str = Form(...),
    student_name: str = Form(""),
    academy_name: str = Form(""),
    group_id: str = Form(""),
    item_groups_json: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """
    단일 학생 제출 (프런트 수동 그룹핑 모드).
    item_groups_json = [{"item_number": 1, "image_keys": [0, 1], "problem_type": "..."}, ...]
    image_keys 는 files 의 0-based 인덱스.
    """
    try:
        item_groups_raw = json.loads(item_groups_json)
    except Exception:
        raise HTTPException(400, "item_groups_json 파싱 실패")

    submission_id = uuid.uuid4().hex[:12]
    save_dir = UPLOAD_DIR / submission_id
    save_dir.mkdir(parents=True, exist_ok=True)

    # 파일 저장 + 인덱스 매핑
    saved_paths = []
    for f in files:
        dest = save_dir / f.filename
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved_paths.append(str(dest))

    # item_groups 재구성 (image_keys → image_paths)
    item_groups = []
    for g in item_groups_raw:
        keys = g.get("image_keys", [])
        paths = [saved_paths[k] for k in keys if 0 <= k < len(saved_paths)]
        if not paths:
            continue
        item_groups.append({
            "item_number": g.get("item_number", 1),
            "image_paths": paths,
            "problem_id": g.get("problem_id") or None,
            "problem_type": g.get("problem_type", ""),
        })

    if not item_groups:
        raise HTTPException(400, "유효한 문항이 없습니다.")

    # 학생 + 제출 생성
    upsert_student(student_id, name=student_name)
    create_submission(
        submission_id=submission_id,
        student_id=student_id,
        problem_id=None,
        item_groups=item_groups,
        academy_name=academy_name,
    )

    # OCR 백그라운드 — item_id 포함해서 재구성
    db = SessionLocal()
    try:
        item_rows = db.query(SubmissionItemORM).filter_by(
            submission_id=submission_id
        ).all()
        ocr_groups = [
            {
                "item_id": r.item_id,
                "item_number": r.item_number,
                "image_paths": r.image_paths or [],
                "problem_id": r.problem_id,
            }
            for r in item_rows
        ]
    finally:
        db.close()

    background_tasks.add_task(_run_ocr_safe, submission_id, ocr_groups)
    return {"submission_id": submission_id, "status": "processing"}


# ═══════════════════════════════════════════════════════════════
# 4. 상태 / 리포트 조회
# ═══════════════════════════════════════════════════════════════
@router.get("/api/status/{submission_id}")
def get_status(submission_id: str):
    status = get_submission_status(submission_id)
    if status is None:
        raise HTTPException(404, "제출 ID를 찾을 수 없습니다.")
    return {"submission_id": submission_id, "status": status}


@router.get("/api/report/{submission_id}")
def get_report(submission_id: str):
    sub = get_submission(submission_id)
    if sub is None:
        raise HTTPException(404, "리포트를 찾을 수 없습니다.")
    return sub


@router.get("/api/report/{submission_id}/pdf")
def get_report_pdf(submission_id: str):
    """평가 리포트 PDF 다운로드"""
    sub = get_submission(submission_id)
    if sub is None:
        raise HTTPException(404, "리포트를 찾을 수 없습니다.")

    out_path = str(REPORT_DIR / f"{submission_id}.pdf")
    try:
        generate_pdf(sub, out_path)
    except Exception as e:
        logger.error(f"PDF 생성 실패: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(500, f"PDF 생성 실패: {str(e)}")

    student_name = sub.get("student_name") or sub.get("student_id") or "report"
    filename = f"논술_성적_리포트_{student_name}.pdf"
    return FileResponse(out_path, filename=filename, media_type="application/pdf")


# ═══════════════════════════════════════════════════════════════
# 5. 문항별 작업 (OCR 수정, 첨삭, 교사 검토)
# ═══════════════════════════════════════════════════════════════
class OcrUpdatePayload(BaseModel):
    corrected_text: str


@router.post("/api/item/{item_id}/ocr")
def update_ocr(item_id: str, payload: OcrUpdatePayload):
    """교사가 수정한 OCR 텍스트 저장"""
    update_item_ocr_text(item_id, payload.corrected_text)
    return {"status": "ok"}


class AnnotatePayload(BaseModel):
    ocr_text: str
    problem_id: Optional[str] = None
    item_number: int


@router.post("/api/item/{item_id}/annotate")
def annotate(
    item_id: str,
    payload: AnnotatePayload,
    background_tasks: BackgroundTasks,
):
    """문항별 첨삭 실행 (백그라운드)"""

    def _run():
        # submission_id 찾기
        db = SessionLocal()
        try:
            item = db.query(SubmissionItemORM).filter_by(item_id=item_id).first()
            if not item:
                return
            sid = item.submission_id
        finally:
            db.close()

        try:
            run_annotation(
                submission_id=sid,
                item_id=item_id,
                ocr_text=payload.ocr_text,
                problem_id=payload.problem_id,
                item_number=payload.item_number,
            )
        except Exception as e:
            logger.error(f"첨삭 실패 [{item_id}]: {e}")
            logger.error(traceback.format_exc())

    background_tasks.add_task(_run)
    return {"status": "processing"}


class ReviewPayload(BaseModel):
    numbered_text: Optional[str] = ""
    strengths: Optional[str] = ""
    weaknesses: Optional[str] = ""
    improvements: Optional[str] = ""
    summary: Optional[str] = ""
    score: Optional[float] = None


@router.post("/api/item/{item_id}/review")
def review_item(item_id: str, payload: ReviewPayload):
    """교사 검토 결과 저장"""
    teacher_result = {
        "numbered_text": payload.numbered_text or "",
        "strengths": payload.strengths or "",
        "weaknesses": payload.weaknesses or "",
        "improvements": payload.improvements or "",
        "summary": payload.summary or "",
    }
    save_teacher_item_result(item_id, teacher_result, score=payload.score)
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# 6. 평가 목록 / 삭제
# ═══════════════════════════════════════════════════════════════
@router.get("/api/reports")
def get_reports(
    limit: int = 50,
    student_id: Optional[str] = None,
    status: Optional[str] = None,
):
    return list_submissions(
        student_id=student_id,
        status=status,
        limit=limit,
    )


@router.delete("/api/reports/{submission_id}")
def delete_report(submission_id: str):
    delete_submission(submission_id)
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# 7. 학생 관리
# ═══════════════════════════════════════════════════════════════
class StudentPayload(BaseModel):
    student_id: str
    name: Optional[str] = ""
    grade: Optional[str] = ""
    class_name: Optional[str] = ""
    note: Optional[str] = ""


@router.get("/api/students")
def api_list_students():
    return list_students(limit=500)


@router.post("/api/students")
def api_save_student(payload: StudentPayload):
    upsert_student(
        student_id=payload.student_id,
        name=payload.name or "",
        grade=payload.grade or "",
        class_name=payload.class_name or "",
        note=payload.note or "",
    )
    return {"status": "ok"}


@router.delete("/api/students/{student_id}")
def api_delete_student(student_id: str):
    delete_student(student_id)
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# 8. 논술 문제 관리
# ═══════════════════════════════════════════════════════════════
class ProblemPayload(BaseModel):
    problem_id: str
    title: str
    question: str
    passages: Optional[str] = ""
    sample_answer: Optional[str] = ""
    scoring_criteria: Optional[str] = ""
    prompt_template: Optional[str] = ""
    score_weights: Optional[dict] = None
    system_prompt_id: Optional[str] = None
    subject: Optional[str] = ""
    year: Optional[str] = ""
    university: Optional[str] = ""
    time_limit: Optional[int] = 0


@router.get("/api/problems")
def api_list_problems():
    return list_problems()


@router.post("/api/problems")
def api_save_problem(payload: ProblemPayload):
    return create_or_update_problem(
        problem_id=payload.problem_id,
        title=payload.title,
        question=payload.question,
        passages=payload.passages or "",
        sample_answer=payload.sample_answer or "",
        scoring_criteria=payload.scoring_criteria or "",
        prompt_template=payload.prompt_template or "",
        score_weights=payload.score_weights,
        system_prompt_id=payload.system_prompt_id,
        subject=payload.subject or "",
        year=payload.year or "",
        university=payload.university or "",
        time_limit=payload.time_limit or 0,
    )


@router.get("/api/problems/{problem_id}")
def api_get_problem(problem_id: str):
    p = get_problem(problem_id)
    if not p:
        raise HTTPException(404, "문제를 찾을 수 없습니다.")
    return p


@router.delete("/api/problems/{problem_id}")
def api_delete_problem(problem_id: str):
    delete_problem(problem_id)
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# 9. 문제 그룹 관리
# ═══════════════════════════════════════════════════════════════
class GroupPayload(BaseModel):
    group_id: str
    title: str
    category: str = "reg"
    problem_ids: Optional[list] = None
    vol: Optional[int] = None
    lecture: Optional[int] = None
    university: Optional[str] = ""
    year: Optional[str] = ""
    exam_type: Optional[str] = ""


@router.get("/api/groups")
def api_list_groups(category: Optional[str] = None):
    return list_groups(category=category)


@router.post("/api/groups")
def api_save_group(payload: GroupPayload):
    return create_or_update_group(
        group_id=payload.group_id,
        title=payload.title,
        category=payload.category,
        problem_ids=payload.problem_ids,
        vol=payload.vol,
        lecture=payload.lecture,
        university=payload.university or "",
        year=payload.year or "",
        exam_type=payload.exam_type or "",
    )


@router.get("/api/groups/{group_id}")
def api_get_group(group_id: str):
    g = get_group_with_problems(group_id)
    if not g:
        raise HTTPException(404, "그룹을 찾을 수 없습니다.")
    return g


@router.delete("/api/groups/{group_id}")
def api_delete_group(group_id: str):
    delete_group(group_id)
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# 10. 공통 시스템 프롬프트
# ═══════════════════════════════════════════════════════════════
class SystemPromptPayload(BaseModel):
    prompt_id: str
    name: str
    content: str
    description: Optional[str] = ""
    is_default: Optional[bool] = False


@router.get("/api/system-prompts")
def api_list_prompts():
    return list_system_prompts()


@router.post("/api/system-prompts")
def api_save_prompt(payload: SystemPromptPayload):
    return upsert_system_prompt(
        prompt_id=payload.prompt_id,
        name=payload.name,
        content=payload.content,
        description=payload.description or "",
        is_default=bool(payload.is_default),
    )


@router.get("/api/system-prompts/{prompt_id}")
def api_get_prompt(prompt_id: str):
    p = get_system_prompt(prompt_id)
    if not p:
        raise HTTPException(404, "프롬프트를 찾을 수 없습니다.")
    return p


@router.delete("/api/system-prompts/{prompt_id}")
def api_delete_prompt(prompt_id: str):
    p = get_system_prompt(prompt_id)
    if p and p.get("is_default"):
        raise HTTPException(400, "기본 프롬프트는 삭제할 수 없습니다.")
    # 실제 삭제는 active=False (soft delete) — crud.py 에 맞춰 구현
    # crud.py 에 delete_system_prompt 가 없으면 여기서 간단히 직접:
    from eval_engine.models import SystemPromptORM, get_db
    with get_db() as db:
        sp = db.query(SystemPromptORM).filter_by(prompt_id=prompt_id).first()
        if sp:
            sp.active = False
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# 11. 앱 설정 (LLM provider / model 등)
# ═══════════════════════════════════════════════════════════════
@router.get("/api/settings")
def api_get_settings():
    return {
        "llm_provider": get_llm_provider(),
        "gemini_model": get_gemini_model(),
        "ollama_model": get_ollama_model(),
    }


class SettingsPayload(BaseModel):
    llm_provider: Optional[str] = None
    gemini_model: Optional[str] = None
    ollama_model: Optional[str] = None


@router.post("/api/settings")
def api_save_settings(payload: SettingsPayload):
    if payload.llm_provider:
        set_setting("llm_provider", payload.llm_provider)
    if payload.gemini_model:
        set_setting("gemini_model", payload.gemini_model)
    if payload.ollama_model:
        set_setting("ollama_model", payload.ollama_model)
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# 12. 통계 / 헬스체크
# ═══════════════════════════════════════════════════════════════
@router.get("/api/stats")
def api_stats(problem_id: Optional[str] = None, student_id: Optional[str] = None):
    return get_statistics(student_id=student_id, problem_id=problem_id)


@router.get("/api/health")
def api_health():
    checks = {"status": "ok"}
    checks["gemini_key"] = "✅" if os.getenv("GEMINI_API_KEY") else "❌"
    try:
        import google.generativeai  # noqa
        checks["google_generativeai"] = "✅"
    except ImportError:
        checks["google_generativeai"] = "❌"
    try:
        import reportlab  # noqa
        checks["reportlab"] = "✅"
    except ImportError:
        checks["reportlab"] = "❌"
    return checks

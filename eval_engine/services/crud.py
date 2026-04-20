import uuid
from datetime import datetime
from sqlalchemy import desc
from eval_engine.models import (
    SystemPromptORM, EssayProblemORM, StudentORM,
    SubmissionORM, SubmissionItemORM, ProblemGroupORM,
    AppSettingORM, get_db
)


# ── 공통 시스템 프롬프트 ──────────────────────────────────────

DEFAULT_SYSTEM_PROMPT_CONTENT = """[시스템 역할 설정]
너는 대한민국 최고의 대입 논술연구소에서 20년 이상 근무한 '수석 논술 연구원'이자 '전문 채점 위원'이다. 너의 역할은 기계적인 점수 매기기가 아니라, 학생이 자신의 논리적 허점을 스스로 깨닫고 개선할 수 있도록 분석적이고 입체적인 피드백을 제공하는 것이다.

[수행 원칙]
원문 절대 보존: [학생 답안]의 오탈자, 띄어쓰기, 문장 부호는 1단계(문장 번호 부여)에서 절대 수정하지 말고 입력된 그대로 출력하라. (교정은 2단계 '수정 후'에서만 진행)

맥락 중심 해석: "채점기준에 따르면 ~이다"라는 결과론적 서술을 지양하고, "<문제>의 의도와 <제시문>의 관계를 고려할 때, 이 지점에서는 ~한 논리가 도출되어야 한다"는 식의 추론형 설명을 제공하라.

형식 엄수: 지정된 태그와 항목 외의 이모티콘, 장식용 기호(** 포함)는 일절 사용하지 않는다.

[평가 프로세스]
1단계: 원문 분석 및 번호 부여
[학생 답안]의 내용을 단 한 글자도 바꾸지 말고(오탈자 포함) 각 문장 끝의 종결어미를 기준으로 모든 문장 앞에 번호(❶, ❷, ❸...)를 부여한다.
기존 문단 구분은 유지하되, 문장 간 줄바꿈 없이 연결하여 작성한다.
글자 수 계산: 한글 기준 공백 포함 글자 수를 최대한 정밀하게 측정하여 마지막에 표시한다.

2단계: 입체적 심층 첨삭
아래 형식을 엄격히 준수하여 작성한다.

<장점>
채점기준과 출제의도를 바탕으로 학생이 정확히 포착한 지점, 논리적 연결이 우수한 부분을 문장형으로 서술.

<단점>
핵심 논거 누락, 독해 오류, 논리적 비약 등을 지적. 단순 나열이 아닌 '왜 오류인지'에 대한 근거를 제시문과 연결하여 설명.

<보완할 부분>
(1) ❶ [해당 문장 번호 활용] (격식체 설명)
수정 전: (학생의 원문 그대로 제시)
수정 후: (내용적 보완과 표현 교정이 완료된 문장)
→ 수정 이유: (문제-제시문-답안 간의 논리적 괴리를 해결하는 방향 설명)
(2), (3) 반복...

<총평>
구조적 완성도, 사고의 깊이, 자료 통합력을 종합 평가.
학생의 사고 과정을 추적하여 향후 어떤 독해/쓰기 훈련이 필요한지 제언.

[추가 참고사항]
채점기준은 분석의 토대로 삼되, 설명에서는 문제와 제시문, 출제의도를 고려할 때 ~해야 한다는 논리적 추론의 형태로 풀어낼 것.
단순히 채점기준에 따르면 ~이다라는 결과론적 표현은 피하고, 학생이 스스로 논리 흐름을 납득할 수 있도록 이해 중심의 방향성을 제시할 것.
오탈자나 표현 오류는 수정 후 기준으로 내용적 측면 위주로 첨삭.
초심 잃지 말고 일관성 절대 유지."""


def init_default_system_prompt():
    with get_db() as db:
        if db.query(SystemPromptORM).filter_by(prompt_id="default").first():
            return
        db.add(SystemPromptORM(
            prompt_id="default",
            name="기본 논술 첨삭 프롬프트",
            description="수석 논술 연구원 역할 / 1단계 원문분석 + 2단계 심층첨삭",
            content=DEFAULT_SYSTEM_PROMPT_CONTENT,
            is_default=True, active=True,
        ))


def upsert_system_prompt(prompt_id, name, content, description="", is_default=False):
    with get_db() as db:
        p = db.query(SystemPromptORM).filter_by(prompt_id=prompt_id).first()
        if p is None:
            p = SystemPromptORM(prompt_id=prompt_id)
            db.add(p)
        p.name = name
        p.content = content
        p.description = description
        p.updated_at = datetime.utcnow()
        if is_default:
            db.query(SystemPromptORM).filter(
                SystemPromptORM.prompt_id != prompt_id
            ).update({"is_default": False})
            p.is_default = True
        db.flush()
        db.refresh(p)
        return p.to_dict()


def get_system_prompt(prompt_id):
    with get_db() as db:
        p = db.query(SystemPromptORM).filter_by(prompt_id=prompt_id).first()
        return p.to_dict() if p else None


def get_default_system_prompt():
    with get_db() as db:
        p = db.query(SystemPromptORM).filter_by(is_default=True, active=True).first()
        if p is None:
            p = db.query(SystemPromptORM).filter_by(active=True).first()
        return p.to_dict() if p else None


def list_system_prompts():
    with get_db() as db:
        rows = db.query(SystemPromptORM).filter_by(active=True).order_by(
            SystemPromptORM.is_default.desc(),
            SystemPromptORM.created_at.desc()
        ).all()
        return [r.to_dict() for r in rows]


def resolve_system_prompt_for_problem(problem: dict | None) -> str:
    if problem and problem.get("system_prompt_id"):
        sp = get_system_prompt(problem["system_prompt_id"])
        if sp:
            return sp["content"]
    sp = get_default_system_prompt()
    return sp["content"] if sp else DEFAULT_SYSTEM_PROMPT_CONTENT


# ── 논술 문제 ─────────────────────────────────────────────────

def create_or_update_problem(
    problem_id, title, question, passages="", sample_answer="",
    scoring_criteria="", prompt_template="", score_weights=None,
    system_prompt_id=None, subject="", year="", university="", time_limit=0,
):
    with get_db() as db:
        p = db.query(EssayProblemORM).filter_by(problem_id=problem_id).first()
        if p is None:
            p = EssayProblemORM(problem_id=problem_id)
            db.add(p)
        p.title = title
        p.question = question
        p.passages = passages
        p.sample_answer = sample_answer
        p.scoring_criteria = scoring_criteria
        p.prompt_template = prompt_template
        p.system_prompt_id = system_prompt_id
        p.subject = subject
        p.year = year
        p.university = university
        p.time_limit = time_limit
        p.updated_at = datetime.utcnow()
        if score_weights:
            p.score_weights = score_weights
        db.flush()
        db.refresh(p)
        return p.to_dict()


def get_problem(problem_id):
    with get_db() as db:
        p = db.query(EssayProblemORM).filter_by(problem_id=problem_id).first()
        return p.to_dict() if p else None


def list_problems(active_only=True):
    with get_db() as db:
        q = db.query(EssayProblemORM)
        if active_only:
            q = q.filter(EssayProblemORM.active == True)
        rows = q.order_by(desc(EssayProblemORM.created_at)).all()
        return [
            {
                "problem_id": r.problem_id, "title": r.title,
                "subject": r.subject, "year": r.year,
                "university": r.university, "time_limit": r.time_limit,
                "submission_count": len(r.submissions),
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]


def delete_problem(problem_id):
    with get_db() as db:
        p = db.query(EssayProblemORM).filter_by(problem_id=problem_id).first()
        if p:
            p.active = False


# ── 학생 ─────────────────────────────────────────────────────

def upsert_student(student_id, name="", grade="", class_name="", note=""):
    with get_db() as db:
        s = db.query(StudentORM).filter_by(student_id=student_id).first()
        if s is None:
            s = StudentORM(student_id=student_id)
            db.add(s)
        if name:       s.name = name
        if grade:      s.grade = grade
        if class_name: s.class_name = class_name
        if note:       s.note = note
        s.updated_at = datetime.utcnow()


def get_student(student_id):
    with get_db() as db:
        return db.query(StudentORM).filter_by(student_id=student_id).first()


def list_students(skip=0, limit=100):
    with get_db() as db:
        rows = db.query(StudentORM).order_by(
            StudentORM.grade, StudentORM.class_name, StudentORM.name
        ).offset(skip).limit(limit).all()
        return [
            {
                "student_id": s.student_id, "name": s.name,
                "grade": s.grade, "class_name": s.class_name, "note": s.note,
                "submission_count": len(s.submissions),
            }
            for s in rows
        ]


# ── 제출 & 문항 ───────────────────────────────────────────────

def create_submission(
    submission_id: str,
    student_id: str,
    problem_id: str | None,
    item_groups: list[dict],
    academy_name: str = "",
    submit_date: str = "",
) -> str:
    upsert_student(student_id)
    with get_db() as db:
        sub = SubmissionORM(
            submission_id=submission_id,
            student_id=student_id,
            problem_id=problem_id,
            academy_name=academy_name,
            submit_date=submit_date or datetime.now().strftime("%Y-%m-%d"),
            status="pending",
        )
        db.add(sub)
        for g in item_groups:
            item = SubmissionItemORM(
                item_id=f"{submission_id}_item{g['item_number']}",
                submission_id=submission_id,
                item_number=g["item_number"],
                problem_id=g.get("problem_id"),
                problem_type=g.get("problem_type", ""),
                status="pending",
            )
            item.image_paths = g.get("image_paths", [])
            db.add(item)
    return submission_id


def get_submission(submission_id: str) -> dict | None:
    with get_db() as db:
        sub = db.query(SubmissionORM).filter_by(submission_id=submission_id).first()
        return sub.to_dict() if sub else None


def get_submission_status(submission_id: str) -> str | None:
    with get_db() as db:
        sub = db.query(SubmissionORM).filter_by(submission_id=submission_id).first()
        if sub is None:
            return None
        return sub.status if not sub.error_message else f"error: {sub.error_message}"


def update_submission_status(submission_id: str, status: str, error: str = ""):
    with get_db() as db:
        sub = db.query(SubmissionORM).filter_by(submission_id=submission_id).first()
        if sub:
            sub.status = status
            sub.error_message = error
            sub.updated_at = datetime.utcnow()


def save_item_result(item_id: str, ocr_text: str, ocr_confidence: float,
                     llm_result: dict, score: float | None = None):
    with get_db() as db:
        item = db.query(SubmissionItemORM).filter_by(item_id=item_id).first()
        if item:
            item.ocr_text = ocr_text
            item.ocr_confidence = ocr_confidence
            item.llm_result = llm_result
            if score is not None:
                item.score = score
            item.status = "evaluated"
            item.updated_at = datetime.utcnow()


def save_teacher_item_result(item_id: str, teacher_result: dict,
                              score: float | None = None):
    with get_db() as db:
        item = db.query(SubmissionItemORM).filter_by(item_id=item_id).first()
        if not item:
            return
        item.teacher_result = teacher_result
        if score is not None:
            item.score = score
        item.status = "teacher_done"
        item.updated_at = datetime.utcnow()
        sub = item.submission
        if sub and all(i.status == "teacher_done" for i in sub.items):
            sub.status = "teacher_reviewed"
            sub.updated_at = datetime.utcnow()


def finalize_submission(submission_id: str):
    with get_db() as db:
        sub = db.query(SubmissionORM).filter_by(submission_id=submission_id).first()
        if sub:
            sub.status = "done"
            sub.updated_at = datetime.utcnow()


def list_submissions(student_id=None, problem_id=None, status=None,
                     skip=0, limit=50):
    with get_db() as db:
        q = db.query(SubmissionORM)
        if student_id: q = q.filter(SubmissionORM.student_id == student_id)
        if problem_id: q = q.filter(SubmissionORM.problem_id == problem_id)
        if status:     q = q.filter(SubmissionORM.status == status)
        rows = q.order_by(desc(SubmissionORM.created_at)).offset(skip).limit(limit).all()
        return [
            {
                "submission_id": s.submission_id,
                "student_id":    s.student_id,
                "student_name":  s.student.name if s.student else "",
                "problem_id":    s.problem_id,
                "problem_title": s.problem.title if s.problem else "",
                "item_count":    len(s.items),
                "total_score":   sum(i.score or 0 for i in s.items if i.score),
                "status":        s.status,
                "created_at":    s.created_at.isoformat() if s.created_at else "",
            }
            for s in rows
        ]


def delete_student(student_id: str):
    with get_db() as db:
        s = db.query(StudentORM).filter_by(student_id=student_id).first()
        if s:
            db.delete(s)


def delete_submission(submission_id: str):
    """제출 및 연관 문항 삭제"""
    with get_db() as db:
        sub = db.query(SubmissionORM).filter_by(submission_id=submission_id).first()
        if sub:
            db.delete(sub)


# ── 통계 ─────────────────────────────────────────────────────

def get_statistics(student_id=None, problem_id=None):
    with get_db() as db:
        q = db.query(SubmissionORM).filter(
            SubmissionORM.status.in_(["done", "teacher_reviewed"])
        )
        if student_id: q = q.filter(SubmissionORM.student_id == student_id)
        if problem_id: q = q.filter(SubmissionORM.problem_id == problem_id)
        rows = q.all()
        if not rows:
            return {"count": 0}
        scores = [sum(i.score or 0 for i in r.items) for r in rows]
        return {
            "count":    len(rows),
            "avg_score": round(sum(scores)/len(scores), 1) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "pending_review": sum(1 for r in rows if r.status == "done"),
        }


# ── 문제 그룹 ─────────────────────────────────────────────────

def create_or_update_group(
    group_id: str,
    title: str,
    category: str = "reg",
    problem_ids: list | None = None,
    vol: int | None = None,
    lecture: int | None = None,
    university: str = "",
    year: str = "",
    exam_type: str = "",
) -> dict:
    with get_db() as db:
        g = db.query(ProblemGroupORM).filter_by(group_id=group_id).first()
        if g is None:
            g = ProblemGroupORM(group_id=group_id)
            db.add(g)
        g.title      = title
        g.category   = category
        g.vol        = vol
        g.lecture    = lecture
        g.university = university
        g.year       = year
        g.exam_type  = exam_type
        g.updated_at = datetime.utcnow()
        if problem_ids is not None:
            g.problem_ids = problem_ids
        db.flush()
        db.refresh(g)
        return g.to_dict()


def get_group(group_id: str) -> dict | None:
    with get_db() as db:
        g = db.query(ProblemGroupORM).filter_by(group_id=group_id).first()
        return g.to_dict() if g else None


def list_groups(category: str | None = None) -> list[dict]:
    with get_db() as db:
        q = db.query(ProblemGroupORM).filter_by(active=True)
        if category:
            q = q.filter(ProblemGroupORM.category == category)
        rows = q.order_by(
            ProblemGroupORM.category,
            ProblemGroupORM.vol,
            ProblemGroupORM.lecture,
            ProblemGroupORM.university,
            ProblemGroupORM.year,
        ).all()
        return [r.to_dict() for r in rows]


def delete_group(group_id: str):
    with get_db() as db:
        g = db.query(ProblemGroupORM).filter_by(group_id=group_id).first()
        if g:
            g.active = False


def get_group_with_problems(group_id: str) -> dict | None:
    """그룹 + 소속 문제 상세 정보 반환"""
    g = get_group(group_id)
    if not g:
        return None
    problems = []
    for pid in g["problem_ids"]:
        p = get_problem(pid)
        if p:
            problems.append(p)
    g["problems"] = problems
    return g


# ── OCR 전용 (첨삭 분리) ──────────────────────────────────────

def save_item_ocr(item_id: str, ocr_text: str, ocr_confidence: float):
    """OCR 결과만 저장 — 첨삭은 아직 실행 안 함"""
    with get_db() as db:
        item = db.query(SubmissionItemORM).filter_by(item_id=item_id).first()
        if item:
            item.ocr_text       = ocr_text
            item.ocr_confidence = ocr_confidence
            item.status         = "ocr_done"
            item.updated_at     = datetime.utcnow()
        # submission 상태도 업데이트
        sub = db.query(SubmissionORM).filter_by(
            submission_id=item.submission_id
        ).first() if item else None
        if sub and sub.status == "pending":
            sub.status = "ocr_done"
            sub.updated_at = datetime.utcnow()


def update_item_ocr_text(item_id: str, corrected_text: str):
    """교사가 수정한 OCR 텍스트 저장"""
    with get_db() as db:
        item = db.query(SubmissionItemORM).filter_by(item_id=item_id).first()
        if item:
            item.ocr_text   = corrected_text
            item.status     = "ocr_reviewed"   # 교사 검토 완료
            item.updated_at = datetime.utcnow()


# ── 앱 설정 ──────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with get_db() as db:
        row = db.query(AppSettingORM).filter_by(key=key).first()
        return row.value if row else default


def set_setting(key: str, value: str):
    with get_db() as db:
        row = db.query(AppSettingORM).filter_by(key=key).first()
        if row is None:
            row = AppSettingORM(key=key)
            db.add(row)
        row.value = value
        row.updated_at = datetime.utcnow()


def get_all_settings() -> dict:
    with get_db() as db:
        rows = db.query(AppSettingORM).all()
        return {r.key: r.value for r in rows}


def get_llm_provider() -> str:
    """현재 LLM 프로바이더 반환 (DB 설정 → 환경변수 순)"""
    import os
    db_val = get_setting("llm_provider", "")
    if db_val:
        return db_val
    return os.getenv("LLM_PROVIDER", "gemini")


def get_ollama_model() -> str:
    import os
    db_val = get_setting("ollama_model", "")
    if db_val:
        return db_val
    return os.getenv("OLLAMA_MODEL", "gemma3:12b")


def get_gemini_model() -> str:
    import os
    db_val = get_setting("gemini_model", "")
    if db_val:
        return db_val
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

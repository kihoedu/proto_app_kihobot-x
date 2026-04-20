"""
문항별 파이프라인 — OCR / 첨삭 분리

흐름:
  1. run_ocr_only()   → 이미지 → OCR → DB 저장 (status: ocr_done)
  2. 교사가 UI에서 OCR 텍스트 검토·수정 (status: ocr_reviewed)
  3. run_annotation() → 수정된 텍스트 → LLM 첨삭 → DB 저장 (status: evaluated)
"""
import os, base64
from pathlib import Path

import google.generativeai as genai
from eval_engine.services.crud import (
    get_problem, resolve_system_prompt_for_problem,
    save_item_ocr, save_item_result, update_submission_status, finalize_submission,
)
from eval_engine.agents.annotation_agent import annotate_item


# ── 헤더 파싱 ────────────────────────────────────────────────

def parse_answer_sheet_header(image_path: str, api_key: str) -> dict:
    """
    원고지 헤더에서 학생 정보 + 문항 정보 자동 추출
    반환: {
        student_name, academy_name, submit_date,
        vol, lecture, item_number, exam_type,
        group_id (자동 조합)
    }
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    suffix_mime = {
        ".jpg":"image/jpeg",".jpeg":"image/jpeg",
        ".png":"image/png",".webp":"image/webp",".pdf":"application/pdf",
    }
    suffix = Path(image_path).suffix.lower()
    mime = suffix_mime.get(suffix, "image/jpeg")
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()

    prompt = """이 원고지 이미지의 상단 헤더 영역에서 정보를 추출하세요.

헤더 구조:
- 첫 번째 행: 소속학원 | 첨삭담임 | 작성일자 | 학생이름
- 두 번째 행: 과정 | 교재명 | 강의회차 | 문항정보 | 문항번호
- 세 번째 행: 기본과정 | (  )권 | (  )강 | 실전문제□(  )번 / 연습문제□(  )번

아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{
  "student_name": "학생 이름 (없으면 빈 문자열)",
  "academy_name": "소속학원명 (없으면 빈 문자열)",
  "submit_date": "작성일자 (없으면 빈 문자열)",
  "vol": 권 숫자 (없으면 null),
  "lecture": 강 숫자 (없으면 null),
  "item_number": 문항번호 숫자 (없으면 null),
  "exam_type": "실전문제 또는 연습문제 (없으면 빈 문자열)"
}"""

    import json as _json
    try:
        response = model.generate_content([
            prompt,
            {"inline_data": {"mime_type": mime, "data": data}}
        ])
        raw = response.text.strip()
        # JSON 파싱
        raw = raw.replace("```json","").replace("```","").strip()
        result = _json.loads(raw)

        # group_id 자동 조합
        vol = result.get("vol")
        lec = result.get("lecture")
        if vol and lec:
            result["group_id"] = f"reg_{vol}_{str(lec).zfill(2)}"
            result["problem_id"] = f"reg_{vol}_{str(lec).zfill(2)}_{result.get('item_number','1')}"
        else:
            result["group_id"] = ""
            result["problem_id"] = ""

        return result
    except Exception as e:
        return {
            "student_name": "", "academy_name": "", "submit_date": "",
            "vol": None, "lecture": None, "item_number": None,
            "exam_type": "", "group_id": "", "problem_id": "",
            "error": str(e)
        }


def parse_multiple_headers(image_paths: list[str], api_key: str) -> list[dict]:
    """여러 이미지의 헤더를 순서대로 파싱"""
    results = []
    for path in image_paths:
        result = parse_answer_sheet_header(path, api_key)
        result["image_path"] = path
        results.append(result)
    return results


# ── OCR ──────────────────────────────────────────────────────

def _build_ocr_prompt(page_count: int, problem: dict | None) -> str:
    """문제 정보를 포함한 OCR 프롬프트 생성"""

    # 문제 컨텍스트 구성
    context = ""
    if problem:
        parts = []
        if problem.get("question"):
            parts.append(f"[문제]\n{problem['question'][:500]}")
        if problem.get("passages"):
            # 제시문에서 핵심 키워드 추출용으로 앞 300자만
            parts.append(f"[제시문 일부]\n{problem['passages'][:300]}")
        if problem.get("scoring_criteria"):
            parts.append(f"[채점 기준 일부]\n{problem['scoring_criteria'][:200]}")
        if parts:
            context = """
[참고: 이 답안이 다루는 문제 정보]
""" + "\n\n".join(parts) + """

위 문제 정보를 참고하여 전문 용어, 고유명사, 개념어를 정확히 인식하세요.
특히 문제에 등장하는 핵심 개념어(예: 비경합성, 비배제성, 조건부 의무 등)가
손글씨에서 유사하게 보이는 다른 단어로 오인식되지 않도록 주의하세요.
"""

    return f"""당신은 한국어 손글씨 OCR 전문가입니다.
아래 이미지는 학생이 박기호논술 원고지에 손으로 작성한 논술 답안입니다 (총 {page_count}페이지).

[원고지 구조 안내]
이 원고지는 세 영역으로 구성됩니다:
- 상단 헤더: 학생 정보, 문항 정보 (무시)
- 왼쪽 원고지 칸: 학생이 쓴 답안 텍스트 (★ 이 부분만 추출)
- 오른쪽 첨삭란: 강사 첨삭 공간 (무시)

반드시 왼쪽 원고지 칸의 손글씨 답안 텍스트만 추출하세요.
헤더와 오른쪽 첨삭란의 내용은 절대 포함하지 마세요.
{context}
다음 규칙을 엄격히 따라 텍스트를 추출하세요:

[핵심 규칙]
1. 원고지의 물리적 줄바꿈(행 바뀜)은 무시하고, 문장을 자연스럽게 이어서 출력
2. 문단이 실제로 바뀌는 경우(들여쓰기로 새 문단 시작)에만 빈 줄(\n\n)로 구분
3. 원고지 한 행이 끝나고 다음 행으로 이어지는 것은 줄바꿈 없이 붙여서 출력
4. 읽기 어려운 글자는 [?]로 표시
5. 수정된 글자(줄 그어 고침 등)는 최종 수정본 기준으로 읽음
6. 마지막에 ---신뢰도: XX% 형식으로 인식 신뢰도 표시

[예시]
잘못된 출력: "공공재 무임승차의 원인은\n비경합성과 비배제성이다."
올바른 출력: "공공재 무임승차의 원인은 비경합성과 비배제성이다."

답안 텍스트만 출력하고 다른 설명은 추가하지 마세요."""


def _ocr_images(image_paths: list[str], api_key: str,
                problem: dict | None = None) -> tuple[str, float]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    suffix_mime = {
        ".jpg":"image/jpeg",".jpeg":"image/jpeg",
        ".png":"image/png",".webp":"image/webp",".pdf":"application/pdf",
    }
    page_count = len(image_paths)
    prompt = _build_ocr_prompt(page_count, problem)

    parts = [prompt]
    for path in image_paths:
        suffix = Path(path).suffix.lower()
        mime = suffix_mime.get(suffix, "image/jpeg")
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        parts.append({"inline_data": {"mime_type": mime, "data": data}})

    response = model.generate_content(parts)
    raw = response.text.strip()

    confidence = 0.85
    if "---신뢰도:" in raw:
        lines = raw.split("\n")
        for line in reversed(lines):
            if "신뢰도:" in line:
                try:
                    pct = line.split("신뢰도:")[1].strip().replace("%","")
                    confidence = float(pct) / 100.0
                    raw = "\n".join(l for l in lines if "신뢰도:" not in l).strip()
                except Exception:
                    pass
                break
    return raw, confidence


def run_ocr_only(
    submission_id: str,
    item_groups: list[dict],  # [{"item_id":"...","item_number":1,"image_paths":[...]}]
):
    """1단계: OCR만 실행 → status: ocr_done"""
    api_key = os.getenv("GEMINI_API_KEY","")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 환경변수가 없습니다.")

    update_submission_status(submission_id, "ocr_processing")

    # 각 문항의 problem_id를 DB에서 로드 (OCR 정확도 향상용)
    from eval_engine.models import SessionLocal, SubmissionItemORM
    db = SessionLocal()
    item_problem_map = {}
    try:
        for g in item_groups:
            row = db.query(SubmissionItemORM).filter_by(item_id=g["item_id"]).first()
            if row and row.problem_id:
                item_problem_map[g["item_id"]] = row.problem_id
    finally:
        db.close()

    for g in item_groups:
        try:
            # 파이프라인에서 직접 받은 problem_id 우선, 없으면 DB에서 조회
            pid = g.get("problem_id") or item_problem_map.get(g["item_id"])
            problem = get_problem(pid) if pid else None

            ocr_text, ocr_confidence = _ocr_images(g["image_paths"], api_key, problem)
            save_item_ocr(g["item_id"], ocr_text, ocr_confidence)
        except Exception as e:
            save_item_ocr(g["item_id"], f"[OCR 오류: {e}]", 0.0)

    update_submission_status(submission_id, "ocr_done")


def run_annotation(
    submission_id: str,
    item_id: str,
    ocr_text: str,           # 교사가 검토·수정한 텍스트
    problem_id: str | None,
    item_number: int,
):
    """2단계: 단일 문항 첨삭 실행"""
    # problem_id 미제공 시 DB에서 item의 problem_id 로드
    if not problem_id:
        from eval_engine.models import SessionLocal, SubmissionItemORM
        db = SessionLocal()
        try:
            item_row = db.query(SubmissionItemORM).filter_by(item_id=item_id).first()
            if item_row:
                problem_id = item_row.problem_id
        finally:
            db.close()
    problem       = get_problem(problem_id) if problem_id else None
    system_prompt = resolve_system_prompt_for_problem(problem)

    llm_result = annotate_item(
        ocr_text=ocr_text,
        problem=problem,
        system_prompt_content=system_prompt,
        item_number=item_number,
    )
    save_item_result(
        item_id=item_id,
        ocr_text=ocr_text,
        ocr_confidence=1.0,   # 교사 검토 완료본이므로 신뢰도 100%
        llm_result=llm_result,
        score=llm_result.get("score"),
    )
    return llm_result

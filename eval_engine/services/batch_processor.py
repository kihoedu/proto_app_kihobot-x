"""
PDF/이미지 일괄 처리 모듈

기능:
1. PDF → 페이지별 이미지 변환
2. 각 페이지 헤더 분석 (학생명 + 문항번호)
3. 학생별/문항별 자동 그룹핑
4. 일괄 제출 생성
"""
import os, base64, uuid, json
from pathlib import Path
from typing import Optional
import google.generativeai as genai


def pdf_to_images(pdf_path: str, output_dir: str) -> list[str]:
    """PDF를 페이지별 이미지로 변환. 반환: 이미지 경로 리스트"""
    try:
        from pdf2image import convert_from_path
        poppler_path = os.getenv("POPPLER_PATH") or None
        pages = convert_from_path(pdf_path, dpi=200)
        saved = []
        for i, page in enumerate(pages):
            img_path = str(Path(output_dir) / f"page_{i+1:03d}.jpg")
            page.save(img_path, "JPEG", quality=90)
            saved.append(img_path)
        return saved
    except ImportError:
        # pdf2image 없으면 원본 PDF 그대로 반환 (Gemini가 직접 처리)
        return [pdf_path]
    except Exception as e:
        print(f"PDF 변환 오류: {e}")
        return [pdf_path]


def analyze_page_header(image_path: str, api_key: str) -> dict:
    """
    단일 페이지 헤더 분석
    반환: {student_name, academy_name, vol, lecture, item_number, exam_type, ...}
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    suffix_mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf",
    }
    suffix = Path(image_path).suffix.lower()
    mime = suffix_mime.get(suffix, "image/jpeg")

    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()

    prompt = """이 원고지 이미지의 상단 헤더에서 정보를 추출하세요.

헤더 구조 (박기호논술 원고지):
- 소속학원 | 첨삭담임 | 작성일자 | 학생이름
- 과정 | 교재명 | 강의회차 | 문항정보 | 문항번호
- 기본과정 | ( )권 | ( )강 | 실전문제□( )번 / 연습문제□( )번

반드시 아래 JSON 형식으로만 응답 (다른 텍스트 없이):
{
  "student_name": "학생 이름",
  "academy_name": "소속학원명",
  "submit_date": "작성일자",
  "vol": 권 숫자 또는 null,
  "lecture": 강 숫자 또는 null,
  "item_number": 문항번호 숫자 또는 null,
  "exam_type": "실전문제 또는 연습문제"
}"""

    try:
        response = model.generate_content([
            prompt,
            {"inline_data": {"mime_type": mime, "data": data}}
        ])
        raw = response.text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)

        vol = result.get("vol")
        lec = result.get("lecture")
        num = result.get("item_number")

        if vol and lec:
            result["group_id"] = f"reg_{vol}_{str(lec).zfill(2)}"
        else:
            result["group_id"] = ""

        if vol and lec and num:
            result["problem_id"] = f"reg_{vol}_{str(lec).zfill(2)}_{num}"
        else:
            result["problem_id"] = ""

        result["image_path"] = image_path
        return result

    except Exception as e:
        return {
            "student_name": "", "academy_name": "", "submit_date": "",
            "vol": None, "lecture": None, "item_number": None,
            "exam_type": "", "group_id": "", "problem_id": "",
            "image_path": image_path, "error": str(e)
        }


def group_pages_by_student_and_item(page_infos: list[dict]) -> dict:
    """
    페이지 정보 리스트 → 학생별/문항별 그룹핑

    반환 구조:
    {
      "홍길동": {
        "group_id": "reg_1_05",
        "academy_name": "박기호논술",
        "submit_date": "...",
        "items": {
          1: {"problem_id": "reg_1_05_1", "image_paths": [...], "problem_type": "실전문제"},
          2: {"problem_id": "reg_1_05_2", "image_paths": [...], "problem_type": "실전문제"},
        }
      }
    }
    """
    grouped = {}

    for info in page_infos:
        name = info.get("student_name", "").strip()
        if not name:
            name = "미확인"

        item_num = info.get("item_number")
        image_path = info.get("image_path", "")
        group_id = info.get("group_id", "")
        problem_id = info.get("problem_id", "")

        if name not in grouped:
            grouped[name] = {
                "group_id": group_id,
                "academy_name": info.get("academy_name", ""),
                "submit_date": info.get("submit_date", ""),
                "items": {}
            }
        # group_id 업데이트 (처음 유효한 값으로)
        if not grouped[name]["group_id"] and group_id:
            grouped[name]["group_id"] = group_id

        if item_num:
            if item_num not in grouped[name]["items"]:
                grouped[name]["items"][item_num] = {
                    "problem_id": problem_id,
                    "image_paths": [],
                    "problem_type": info.get("exam_type", ""),
                }
            grouped[name]["items"][item_num]["image_paths"].append(image_path)
        else:
            # 문항번호 인식 실패 → 미분류
            if "unassigned" not in grouped[name]["items"]:
                grouped[name]["items"]["unassigned"] = {
                    "problem_id": "",
                    "image_paths": [],
                    "problem_type": "",
                }
            grouped[name]["items"]["unassigned"]["image_paths"].append(image_path)

    return grouped


def process_uploaded_files(
    file_paths: list[str],
    api_key: str,
    tmp_dir: str,
) -> dict:
    """
    업로드된 파일들(이미지/PDF) 처리
    PDF는 페이지별 분리 후 헤더 분석
    반환: {grouped, page_infos}
    """
    all_page_infos = []
    last_info = {}  # 가장 최근 유효한 헤더 정보

    for fp in file_paths:
        suffix = Path(fp).suffix.lower()
        if suffix == ".pdf":
            pages = pdf_to_images(fp, tmp_dir)
        else:
            pages = [fp]

        for page_path in pages:
            info = analyze_page_header(page_path, api_key)

            # 헤더 정보 이어받기 — 비어있는 필드는 최근 유효값으로 채움
            # item_number는 이어받지 않음 (페이지마다 다른 문항일 수 있음)
            for key in ("student_name", "academy_name", "submit_date", "vol", "lecture"):
                if not info.get(key) and last_info.get(key):
                    info[key] = last_info[key]

            # item_number가 null이고 이전 페이지와 학생/강의 정보가 같으면
            # 마지막으로 인식된 item_number와 같은 문항의 추가 페이지로 간주
            if not info.get("item_number") and last_info.get("item_number"):
                same_student = (info.get("student_name") == last_info.get("student_name"))
                same_lecture = (info.get("vol") == last_info.get("vol") and
                                info.get("lecture") == last_info.get("lecture"))
                if same_student and same_lecture:
                    info["item_number"] = last_info["item_number"]

            # group_id / problem_id 재계산
            vol = info.get("vol")
            lec = info.get("lecture")
            num = info.get("item_number")
            if vol and lec:
                info["group_id"] = f"reg_{vol}_{str(lec).zfill(2)}"
            if vol and lec and num:
                info["problem_id"] = f"reg_{vol}_{str(lec).zfill(2)}_{num}"

            # 유효한 정보를 last_info에 업데이트
            for key in ("student_name", "academy_name", "submit_date", "vol", "lecture", "item_number"):
                if info.get(key):
                    last_info[key] = info[key]

            all_page_infos.append(info)

    grouped = group_pages_by_student_and_item(all_page_infos)

    return {
        "grouped": grouped,
        "page_infos": all_page_infos,
        "total_pages": len(all_page_infos),
        "total_students": len(grouped),
    }

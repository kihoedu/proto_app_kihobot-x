import base64
import os
from pathlib import Path
from PIL import Image
import google.generativeai as genai
from eval_engine.services.schemas import EssayEvalState


def _encode_image(path: str) -> tuple[str, str]:
    """이미지를 base64로 인코딩, mime type 반환"""
    suffix = Path(path).suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
                ".pdf": "application/pdf"}
    mime = mime_map.get(suffix, "image/jpeg")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return data, mime


def _build_ocr_prompt(page_count: int) -> str:
    return f"""당신은 한국어 손글씨 OCR 전문가입니다.
아래 이미지는 학생이 원고지에 손으로 작성한 논술 답안입니다 (총 {page_count}페이지).

다음 규칙을 따라 정확하게 텍스트를 추출하세요:
1. 원고지 칸에 쓴 글자를 순서대로 읽어 연속된 문장으로 출력
2. 줄바꿈은 문단이 바뀔 때만 \\n\\n으로 표시
3. 읽기 어려운 글자는 [?]로 표시
4. 수정된 글자(줄 그어 고침 등)는 최종 수정본 기준으로 읽음
5. 제목이 있으면 첫 줄에 **제목: xxx** 형식으로 표시
6. OCR 완료 후 마지막에 "---신뢰도: XX%" 형식으로 인식 신뢰도 표시

텍스트만 출력하고, 다른 설명은 추가하지 마세요."""


def ocr_node(state: EssayEvalState) -> EssayEvalState:
    """Gemini Vision으로 손글씨 논술 OCR"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-pro")

    image_paths = state.image_paths
    if not image_paths:
        state.error = "이미지 경로가 없습니다."
        return state

    # 멀티페이지 처리: 모든 이미지를 하나의 요청으로
    parts = [_build_ocr_prompt(len(image_paths))]
    for path in image_paths:
        data, mime = _encode_image(path)
        parts.append({"inline_data": {"mime_type": mime, "data": data}})

    response = model.generate_content(parts)
    raw_text = response.text.strip()

    # 신뢰도 파싱
    confidence = 0.85  # 기본값
    if "---신뢰도:" in raw_text:
        lines = raw_text.split("\n")
        for line in reversed(lines):
            if "신뢰도:" in line:
                try:
                    pct = line.split("신뢰도:")[1].strip().replace("%", "")
                    confidence = float(pct) / 100.0
                    raw_text = "\n".join(
                        l for l in lines if "신뢰도:" not in l
                    ).strip()
                except Exception:
                    pass
                break

    state.ocr_text = raw_text
    state.ocr_confidence = confidence
    return state


def ocr_node_dict(state: dict) -> dict:
    """LangGraph dict 인터페이스용 래퍼"""
    s = EssayEvalState(**state)
    result = ocr_node(s)
    return result.model_dump()

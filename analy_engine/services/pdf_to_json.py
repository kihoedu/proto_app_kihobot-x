#!/usr/bin/env python3
"""
PDF → JSON 변환 모듈
=====================
PDF 구조를 자동 감지하여 처리:
  [A] 문항카드 통합형 (성균관대 선행학습 보고서 등)
      → 문제카드 단위로 분리 → 카드별로 Gemini 호출
  [B] 1부/2부 분리형 (문제지 + 해설지 섹션이 구분된 형식)
      → 기존 split_parts() 로직 유지
  [C] 문제만 있는 형식 (해설 없음)
      → 1부만 처리

출력 JSON 스키마는 항상 동일:
{
  "meta": { "university", "year", "track", "subtitle", "examTime" },
  "problemSets": [
    {
      "number": 1,
      "instructions": "",
      "passages": [{"label","text","source","textbook"}],
      "question": {"text","wordCount","points"},
      "출제의도": "",
      "문제해설": "",
      "sampleAnswer": "",
      "rubric": "",
      "rubricTable": [],
      "commentary": [{"label","text"}]
    }
  ]
}
"""
import os, sys, json, subprocess, re
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

POPPLER_PATH = os.getenv("POPPLER_PATH", r"C:\projects\ocr_pipeline\poppler-24.08.0\Library\bin")
PDFTOTEXT = os.path.join(POPPLER_PATH, "pdftotext.exe") if os.name == "nt" else "pdftotext"


# ────────────────────────────────────────────────────────────
# 텍스트 추출
# ────────────────────────────────────────────────────────────
def extract_text(pdf_path: str) -> str:
    result = subprocess.run(
        [PDFTOTEXT, "-layout", pdf_path, "-"],
        capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext 실패: {result.stderr}")
    print(f"📝 텍스트 추출 ({len(result.stdout)}자)")
    return result.stdout


# ────────────────────────────────────────────────────────────
# PDF 구조 감지
# ────────────────────────────────────────────────────────────
def detect_structure(raw: str) -> str:
    """
    반환값:
      'card'   : 문항카드 통합형 (성균관대 보고서 등)
      'split'  : 1부/2부 분리형
      'simple' : 문제만 있는 단순형
    """
    # 문항카드 형식 감지: "문항카드" 키워드 OR (출제의도+채점기준+예시답안이 섞여있음)
    card_markers = len(re.findall(r'문항\s*카드', raw))
    has_card = card_markers >= 1

    # 출제의도/채점기준/예시답안이 문제 번호별로 반복되는지
    intent_count = len(re.findall(r'출\s*제\s*의\s*도', raw))
    rubric_count = len(re.findall(r'채\s*점\s*기\s*준', raw))
    sample_count = len(re.findall(r'예\s*시\s*답\s*안', raw))

    if has_card or (intent_count >= 2 and rubric_count >= 2):
        return 'card'

    # 1부/2부 분리 감지: 문제해설 섹션이 후반에 몰려있음
    half = len(raw) // 2
    intent_first = len(re.findall(r'출\s*제\s*의\s*도', raw[:half]))
    intent_second = len(re.findall(r'출\s*제\s*의\s*도', raw[half:]))
    if intent_second > intent_first and intent_second >= 1:
        return 'split'

    if intent_count >= 1 or rubric_count >= 1:
        return 'split'

    return 'simple'


# ────────────────────────────────────────────────────────────
# [A] 문항카드형 — 카드 단위 분리
# ────────────────────────────────────────────────────────────
def split_card_sections(raw: str) -> list:
    """
    문항카드 경계를 찾아 카드별 텍스트 리스트 반환.
    각 카드는 문제번호, 제시문, 출제의도, 채점기준, 예시답안을 모두 포함.

    경계 패턴 예:
      < 1> 문항카드  /  <문항카드 1>  /  문항카드 논술시험 ... 문제 [1]
    """
    # 다양한 문항카드 시작 패턴 (우선순위 순)
    boundary_patterns = [
        r'<\s*문항\s*카드\s*\d+\s*>',           # <문항카드 1>  ← 성균관대 실제 패턴
        r'<\s*\d+\s*>.*?문항\s*카드',            # < 1> ... 문항카드
        r'문항\s*카드\s*\d+',                    # 문항카드 1
        r'문항\s*카드\s*논술\s*시험',             # 문항카드 논술시험
    ]

    combined = '|'.join(boundary_patterns)
    matches = list(re.finditer(combined, raw, re.MULTILINE))

    if not matches:
        # 경계를 못 찾은 경우: 출제의도/채점기준/예시답안으로 카드 추정
        # 각 "출제 의도" 앞에 있는 제시문 섹션을 기준으로 분리
        return _split_by_question_number(raw)

    cards = []
    for i, m in enumerate(matches):
        # 카드 시작은 매치 위치 앞의 줄 시작으로
        line_start = raw.rfind('\n', 0, m.start())
        start = line_start + 1 if line_start != -1 else m.start()
        end = len(raw)
        if i + 1 < len(matches):
            next_line = raw.rfind('\n', 0, matches[i+1].start())
            end = next_line + 1 if next_line != -1 else matches[i+1].start()
        card_text = raw[start:end].strip()
        if card_text:
            cards.append(card_text)

    return cards


def _split_by_question_number(raw: str) -> list:
    """
    문항카드 경계를 못 찾은 경우 fallback:
    '문제 [N]' 또는 '[문제 N]' 앞을 기준으로 분리.
    """
    pat = r'\n(?=.*?\[문제\s*\d+\].*?\n.*?제시문)'
    parts = re.split(pat, raw)
    return [p.strip() for p in parts if len(p.strip()) > 200]


# ────────────────────────────────────────────────────────────
# [B] 1부/2부 분리형
# ────────────────────────────────────────────────────────────
def split_parts(raw: str):
    """1부(문제)와 2부(해설) 분리 — 기존 로직 유지"""
    patterns = [
        r'인문계열.*문제해설',
        r'자연계열.*문제해설',
        r'\d{4}학년도.*문제해설',
    ]
    best = len(raw)
    for pat in patterns:
        m = re.search(pat, raw)
        if m and m.start() < best:
            ls = raw.rfind("\n", 0, m.start())
            best = max(0, ls) if ls != -1 else m.start()

    if best == len(raw):
        m = re.search(r'\f[^\f]*?출\s*제\s*의\s*도', raw)
        if m:
            ps = raw.rfind("\f", 0, m.start() + 1)
            if ps != -1: best = ps

    if best >= len(raw) - 100:
        return raw, ""
    return raw[:best].strip(), raw[best:].strip()


def split_part2_by_problem(text: str) -> list:
    """2부 해설 텍스트를 문제별로 분할"""
    splits = []
    patterns = [
        r'문제\s*\.?\s*0?(\d+)',
        r'\[문제\s*(\d+)\]',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text):
            num = int(m.group(1))
            context_before = text[max(0, m.start()-100):m.start()]
            context_after = text[m.end():min(len(text), m.end()+200)]
            if '출제의도' in context_before or '출제의도' in context_after:
                splits.append((m.start(), num))

    if not splits:
        return [text]

    seen_nums = set()
    unique_splits = []
    for pos, num in sorted(splits):
        if num not in seen_nums:
            seen_nums.add(num)
            unique_splits.append((pos, num))

    chunks = []
    for i, (pos, num) in enumerate(unique_splits):
        start = pos
        line_start = text.rfind("\n", max(0, start - 50), start)
        if line_start != -1:
            start = line_start
        end = unique_splits[i+1][0] if i+1 < len(unique_splits) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

    return chunks if chunks else [text]


# ────────────────────────────────────────────────────────────
# Gemini 프롬프트
# ────────────────────────────────────────────────────────────

SYSTEM_CARD = """당신은 대학 논술 기출문제 '문항카드' 텍스트에서 구조화된 JSON을 추출하는 전문가입니다.

하나의 문항카드 텍스트가 주어집니다. 이 카드에는 아래 요소들이 포함되어 있습니다:
- 문제 번호 및 지시문
- 제시문 [가], [나], ... (또는 <제시문 1>, <제시문 2> 등 다양한 표기)
- 문제(논제)
- 출제의도
- 문항해설 (또는 채점기준 설명)
- 채점기준
- 예시답안

## 핵심 원칙
- 제시문·예시답안 원문은 한 글자도 빠짐없이 정확히 옮길 것
- PDF 추출 과정에서 줄바꿈이 문장 중간에 삽입된 경우가 많음. 같은 문단 내 끊어진 문장은 반드시 자연스럽게 이어붙일 것. 문단 구분(빈 줄 또는 명확한 의미 전환)만 \\n으로 표시.
- 한자, 외국어 그대로 유지
- 제시문이 여러 개면 label을 "[가]", "[나]" 또는 원문 표기("[제시문 1]" 등) 그대로 사용

## 출력: 순수 JSON만 (```json 마크다운 없이)

{
  "number": 1,
  "instructions": "※ 다음 제시문을 읽고 물음에 답하시오.",
  "passages": [
    {
      "label": "[가]",
      "text": "제시문 원문 전체 (문단 구분은 \\n)",
      "source": "저자/출처 (없으면 빈 문자열)",
      "textbook": "『교과서명』 (없으면 빈 문자열)"
    }
  ],
  "question": {
    "text": "문제(논제) 전체 내용",
    "wordCount": "320~400자 (없으면 빈 문자열)",
    "points": 40
  },
  "출제의도": "출제의도 전체 텍스트 (없으면 빈 문자열)",
  "문제해설": "문항해설 전체 텍스트 (없으면 빈 문자열)",
  "sampleAnswer": "예시답안 전체 텍스트 (없으면 빈 문자열)",
  "rubric": "채점기준 텍스트 (배점 포함, 없으면 빈 문자열)",
  "rubricTable": [
    {"grade": "상", "code": "A", "desc": "기준 설명"},
    {"grade": "중", "code": "B", "desc": "기준 설명"},
    {"grade": "하", "code": "C", "desc": "기준 설명"}
  ]
}

rubricTable 규칙:
- 채점 등급 A, B, C → grade: "상"
- 채점 등급 D → grade: "중"
- 채점 등급 E, F → grade: "하"
- S 코드가 있으면 grade: "상"
- 채점 등급표가 없으면 빈 배열 []
"""

SYSTEM_PART1 = """당신은 대학 논술 기출문제 텍스트에서 구조화된 JSON을 추출하는 전문가입니다.
문제지(제시문+문제)만 포함된 텍스트입니다. 해설(출제의도, 채점기준 등)은 없습니다.

## 핵심 원칙
- 제시문 원문은 한 글자도 빠짐없이 정확히 옮길 것
- PDF 추출 과정에서 줄바꿈이 문장 중간에 삽입된 경우, 같은 문단 내 끊어진 문장은 자연스럽게 이어붙일 것. 문단 구분만 \\n으로 표시.
- 한자, 외국어 그대로 유지

## 출력: 순수 JSON만 (```json 마크다운 없이)

{
  "meta": {
    "university": "대학명",
    "year": 2026,
    "track": "인문계열Ⅱ",
    "subtitle": "주제1, 주제2, 주제3",
    "examTime": 100
  },
  "problemSets": [
    {
      "number": 1,
      "instructions": "※ 다음 제시문을 읽고 물음에 답하시오.",
      "passages": [
        {
          "label": "[가]",
          "text": "제시문 원문 전체 (문단 구분은 \\n)",
          "source": "출처 (없으면 빈 문자열)",
          "textbook": "『고등학교 OO』 (없으면 빈 문자열)"
        }
      ],
      "question": {
        "text": "문제 내용",
        "wordCount": "320~400자 (없으면 빈 문자열)",
        "points": 30
      }
    }
  ]
}

주의:
- 같은 지시문 아래 여러 문제가 있으면 제시문은 첫 번째 problemSet에만 넣고, 두 번째 문제부터 별도 problemSet으로 (passages는 빈 배열 or 공유)
"""

SYSTEM_PART2_SINGLE = """당신은 대학 논술 기출문제 해설 텍스트에서 구조화된 JSON을 추출하는 전문가입니다.

## 핵심 원칙
- 원문 한 글자도 빠짐없이 정확히
- PDF 추출 과정에서 줄바꿈이 문장 중간에 삽입된 경우, 같은 문단 내 끊어진 문장은 자연스럽게 이어붙일 것. 문단 구분만 \\n으로 표시.

## 출력: 순수 JSON만 (```json 마크다운 없이)

{
  "number": 1,
  "출제의도": "전체 텍스트 (없으면 빈 문자열)",
  "문제해설": "전체 텍스트 (없으면 빈 문자열)",
  "예시답안": "전체 텍스트 (없으면 빈 문자열)",
  "채점기준_text": "채점 항목 텍스트 배점 포함 (없으면 빈 문자열)",
  "rubricTable": [
    {"grade": "상", "code": "A", "desc": "기준 설명"},
    {"grade": "중", "code": "B", "desc": "기준 설명"},
    {"grade": "하", "code": "C", "desc": "기준 설명"}
  ]
}

rubricTable 규칙:
- 채점 등급이 A~F이면 grade는 A/B/C → "상", D → "중", E/F → "하"
- 채점 등급표가 없으면 빈 배열 []
"""


# ────────────────────────────────────────────────────────────
# JSON 정리
# ────────────────────────────────────────────────────────────
def clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    return text.strip()


def build_commentary(ps: dict) -> list:
    """passages 기반으로 commentary 자동 생성"""
    result = []
    for p in ps.get("passages", []):
        parts = [p.get("text", "")]
        if p.get("source"):
            parts.append(p["source"])
        if p.get("textbook"):
            parts.append(f"-{p['textbook']}")
        result.append({"label": p.get("label", ""), "text": "\n".join(parts)})
    return result


def fill_defaults(ps: dict) -> dict:
    """problemSet에 누락된 필드 기본값 채우기"""
    defaults = {
        "출제의도": "",
        "문제해설": "",
        "sampleAnswer": "",
        "rubric": "",
        "rubricTable": [],
    }
    for k, v in defaults.items():
        if k not in ps:
            ps[k] = v
    if not ps.get("commentary"):
        ps["commentary"] = build_commentary(ps)
    return ps


# ────────────────────────────────────────────────────────────
# Gemini 호출 헬퍼
# ────────────────────────────────────────────────────────────
def call_gemini(client, system: str, user: str, label: str = "",
                max_retries: int = 3) -> dict | None:
    """
    Gemini 호출. 429 발생 시 retryDelay만큼 대기 후 재시도.
    """
    import time
    import re as _re

    for attempt in range(1, max_retries + 1):
        try:
            r = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Part.from_text(text=user)],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.1,
                    max_output_tokens=30000
                )
            )
            result = json.loads(clean_json(r.text))
            if label:
                print(f"  ✅ {label} 완료")
            return result

        except json.JSONDecodeError as e:
            print(f"  ⚠️ {label} JSON 파싱 실패: {e}")
            snippet = r.text[:300] if hasattr(r, "text") else "(응답 없음)"
            print(f"     응답 앞부분: {snippet}")
            return None

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                m = _re.search(r"retry[^0-9]*(\d+(?:\.\d+)?)\s*s", err_str, _re.IGNORECASE)
                wait_sec = float(m.group(1)) + 2 if m else 62
                wait_sec = min(wait_sec, 130)
                if attempt < max_retries:
                    print(f"  ⏳ {label} 429 rate limit — {wait_sec:.0f}초 대기 후 재시도 ({attempt}/{max_retries})...")
                    time.sleep(wait_sec)
                    continue
                else:
                    print(f"  ❌ {label} 429 재시도 {max_retries}회 초과 — 건너뜀")
                    return None
            else:
                print(f"  ⚠️ {label} 호출 실패: {e}")
                return None

    return None


# ────────────────────────────────────────────────────────────
# 메인 변환 로직
# ────────────────────────────────────────────────────────────
def convert_pdf_to_json(pdf_path: str, api_key: str = None) -> dict:
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 필요")

    raw = extract_text(pdf_path)
    if len(raw.strip()) < 100:
        raise ValueError("텍스트 추출 실패 (스캔 PDF?)")

    structure = detect_structure(raw)
    print(f"🔍 PDF 구조 감지: [{structure}]")

    client = genai.Client(api_key=api_key)

    # ── [A] 문항카드 통합형 ──────────────────────────────────
    if structure == 'card':
        cards = split_card_sections(raw)
        print(f"📦 문항카드 {len(cards)}개 감지")

        all_problem_sets = []
        meta = None

        for i, card_text in enumerate(cards):
            label = f"문항카드 {i+1}"
            print(f"🤖 Gemini ({label} → JSON)...")

            result = call_gemini(
                client,
                SYSTEM_CARD,
                f"아래 문항카드 텍스트에서 JSON을 추출하세요.\n"
                f"제시문·예시답안 원문은 한 글자도 빠짐없이.\n\n"
                f"---\n{card_text}\n---",
                label
            )

            if result is None:
                print(f"  ⚠️ {label} 건너뜀")
                continue

            # meta는 첫 번째 카드 또는 전체 텍스트에서 추출
            if meta is None:
                meta = _extract_meta_from_card(card_text, i + 1)

            # number 보정
            if "number" not in result or result["number"] == 0:
                result["number"] = i + 1

            fill_defaults(result)
            all_problem_sets.append(result)

        if not meta:
            meta = _extract_meta_fallback(raw)

        if not all_problem_sets:
            raise RuntimeError(
                "모든 문항카드 추출 실패 (Gemini API 한도 초과 또는 오류). "
                "잠시 후 다시 시도하세요."
            )

        return {"meta": meta, "problemSets": all_problem_sets}

    # ── [B] 1부/2부 분리형 ──────────────────────────────────
    elif structure == 'split':
        t1, t2 = split_parts(raw)
        print(f"📋 1부: {len(t1)}자 / 2부: {len(t2)}자")

        print("🤖 Gemini (1부 → JSON)...")
        data = call_gemini(
            client,
            SYSTEM_PART1,
            f"아래 텍스트에서 1부(문제+제시문) JSON을 추출하세요.\n"
            f"제시문 원문은 한 글자도 빠짐없이.\n\n"
            f"---\n{t1}\n---",
            "1부"
        )
        if data is None:
            raise RuntimeError("1부 JSON 추출 실패")
        print(f"  문제세트: {len(data.get('problemSets', []))}개")

        if t2:
            chunks = split_part2_by_problem(t2)
            all_commentary = []
            for i, chunk in enumerate(chunks):
                label = f"2부 문제{i+1}"
                print(f"🤖 Gemini ({label} → JSON)...")
                c = call_gemini(
                    client,
                    SYSTEM_PART2_SINGLE,
                    f"아래 해설 텍스트에서 JSON을 추출하세요.\n"
                    f"원문 한 글자도 빠짐없이.\n"
                    f"문제 번호(number)는 {i+1}로 설정.\n\n"
                    f"---\n{chunk}\n---",
                    label
                )
                if c:
                    all_commentary.append(c)

            # problemSets에 해설 병합
            for c in all_commentary:
                num = c.get("number", 0)
                for ps in data.get("problemSets", []):
                    if ps["number"] == num:
                        ps["출제의도"] = c.get("출제의도", "")
                        ps["문제해설"] = c.get("문제해설", "")
                        ps["sampleAnswer"] = c.get("예시답안", "")
                        ps["rubric"] = c.get("채점기준_text", "")
                        ps["rubricTable"] = c.get("rubricTable", [])
                        break
        else:
            print("  ⚠️ 2부 없음")

        for ps in data.get("problemSets", []):
            fill_defaults(ps)

        return data

    # ── [C] 단순 문제만 있는 형식 ────────────────────────────
    else:
        print("🤖 Gemini (문제지 → JSON)...")
        data = call_gemini(
            client,
            SYSTEM_PART1,
            f"아래 텍스트에서 문제+제시문 JSON을 추출하세요.\n"
            f"제시문 원문은 한 글자도 빠짐없이.\n\n"
            f"---\n{raw}\n---",
            "문제지"
        )
        if data is None:
            raise RuntimeError("JSON 추출 실패")

        for ps in data.get("problemSets", []):
            fill_defaults(ps)

        return data


# ────────────────────────────────────────────────────────────
# meta 추출 헬퍼
# ────────────────────────────────────────────────────────────
def _extract_meta_from_card(text: str, card_num: int) -> dict:
    """카드 텍스트에서 meta 정보 추출 (정규식 기반)"""
    meta = {
        "university": "",
        "year": 0,
        "track": "",
        "subtitle": "",
        "examTime": 100
    }

    # 연도 추출
    m = re.search(r'(\d{4})\s*학년도', text)
    if m:
        meta["year"] = int(m.group(1))

    # 대학명 추출
    m = re.search(r'(\S+대학교)', text)
    if m:
        meta["university"] = m.group(1)

    # 계열/트랙 추출
    m = re.search(r'(인문|자연|사회|의학|예체능)[^\s]*\s*(계열)?[^\s]*\s*(Ⅰ|Ⅱ|I|II)?', text)
    if m:
        meta["track"] = m.group(0).strip()
    else:
        m = re.search(r'(언어형|수리형|통합형)\s*\d*', text)
        if m:
            meta["track"] = m.group(0).strip()

    # 시험 시간 추출
    m = re.search(r'전체\s*(\d+)\s*분', text)
    if m:
        meta["examTime"] = int(m.group(1))

    return meta


def _extract_meta_fallback(raw: str) -> dict:
    """전체 텍스트에서 meta 추출 (fallback)"""
    return _extract_meta_from_card(raw[:2000], 1)


# ────────────────────────────────────────────────────────────
# 엔트리포인트
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python pdf_to_json.py <PDF경로> [출력JSON경로]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) >= 3 else f"data/{Path(pdf_path).stem}.json"

    data = convert_pdf_to_json(pdf_path)

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 저장: {output}")
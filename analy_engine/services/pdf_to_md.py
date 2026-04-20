#!/usr/bin/env python3
"""
PDF → MD 변환 모듈 (EOLE 매트릭스 포맷)
==========================================
기존 pdf_to_json.py 의 구조 감지 로직을 재활용하면서,
Gemini 출력을 JSON 대신 구조화된 Markdown 으로 받는다.

흐름:
  PDF → pdftotext → 구조감지 (card/split/simple)
       → Gemini (MD 프롬프트) → 구조화 MD
       → frontmatter + 1부문제 + 2부해설 조립

출력 MD 는 한 파일에 전체 교안이 담기며,
사람이 직접 편집 가능하고 DB 저장 · RAG 에 바로 활용 가능하다.
"""
import os
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# 기존 pdf_to_json.py 의 구조 감지 · 텍스트 추출 로직 재활용
from analy_engine.services.pdf_to_json import (
    extract_text,
    detect_structure,
    split_card_sections,
    split_parts,
    split_part2_by_problem,
    _extract_meta_from_card,
    _extract_meta_fallback,
)

# langchain 기반 공통 Gemini 클라이언트
from common.gemini_client import get_llm

load_dotenv()


# ────────────────────────────────────────────────────────────
# MD 출력용 시스템 프롬프트 (EOLE 매트릭스 포맷)
# ────────────────────────────────────────────────────────────

SYSTEM_CARD_MD = """당신은 대학 논술 기출문제 '문항카드' 텍스트를 EOLE 논술 연구소의 매트릭스 교안 포맷(Markdown)으로 변환하는 전문가입니다.

## 🔴 가장 중요한 규칙 — 원본 표기법 보존
**원본이 사용한 제시문 표기를 그대로 유지하세요.**
- 원본이 `[가]`, `[나]`, `[다]` 로 쓰면 → 그대로 `[가]`, `[나]`, `[다]` 사용
- 원본이 `<제시문 1>`, `<제시문 2>` 로 쓰면 → 그대로 `<제시문 1>`, `<제시문 2>` 사용
- 원본이 `(가)`, `(나)`, `(다)` 로 쓰면 → 그대로 `(가)`, `(나)`, `(다)` 사용
- 원본이 `<자료 1>`, `<자료 2>` 로 쓰면 → 그대로 `<자료 1>`, `<자료 2>` 사용
- **절대로 다른 형식으로 변환하지 말 것.** 대학마다 표기가 다르니 원본을 존중하세요.

## 🔴 두 번째로 중요한 규칙 — 출처 정보는 원본에 있을 때만
**원본 텍스트에 출처(저자·책 제목·인용 표시)가 명시된 경우에만** `**출처**:` 줄을 작성하세요.
- 원본에 "-『고등학교 문학』" 같은 표시가 있으면 → `**출처**: 『고등학교 문학』`
- 원본에 "홍길동, 『책제목』" 같은 표시가 있으면 → `**출처**: 홍길동, 『책제목』`
- **원본에 출처 표시가 전혀 없으면 → `**출처**:` 줄 자체를 생략**
- **절대로 출처를 지어내거나 추측하지 말 것.** "출제진", "재구성", "교과서 재구성" 같은 문구를 임의로 붙이지 말 것.

## 출력 규칙
1. 순수 Markdown 만 출력 (```md 마크다운 래퍼 금지)
2. YAML frontmatter 로 시작 (--- 로 감싸기)
3. **YAML 값에 쉼표·괄호가 있으면 반드시 큰따옴표로 감싸기** (예: track: "사회(통합사회, 사회문화)")
4. 아래 섹션 구조를 엄격히 지킬 것
5. 제시문·예시답안 원문은 한 글자도 빠짐없이 정확히 옮길 것
6. PDF 추출 과정에서 문장 중간 줄바꿈은 이어붙이고, 문단 전환에만 빈 줄
7. 한자·외국어 그대로 유지

## 출력 형식 (정확히 이 구조)

---
problem_number: 1
instructions: (지시문)
word_count: (글자수 예: "320~400자")
points: (배점 숫자)
---

# [문제 1]

## 제시문

### (원본 표기 그대로)
(제시문 원문 전체)

(원본에 출처 명시가 있는 경우에만) **출처**: 저자, 『교과서명』

### (다음 제시문 표기)
(제시문 원문)

(원본에 출처가 있는 경우에만) **출처**: ...

## 문제
(논제 내용 전체 · 논제 안의 제시문 참조도 원본 표기 그대로)

---

## 해설

### 출제의도
(출제의도 전체 텍스트 · 원본 표기 그대로)

### 문제해설
(문항해설 전체 텍스트)

### 예시답안
(예시답안 전체 텍스트)

### 채점기준
(채점기준 전체 텍스트 · 배점 포함)

### 채점등급표

| 등급 | 코드 | 기준 |
|------|------|------|
| 상 | A | 설명 |
| 중 | B | 설명 |
| 하 | C | 설명 |

## 채점등급표 변환 규칙
- 원본 A, B, C → "상" / D → "중" / E, F → "하" / S → "상"
- 원본에 등급표 없으면 ### 채점등급표 섹션 전체 생략
"""


SYSTEM_PART1_MD = """당신은 대학 논술 기출 문제지(제시문+문제) 텍스트를 Markdown 으로 변환하는 전문가입니다.
해설(출제의도, 채점기준 등)은 텍스트에 없습니다.

## 🔴 가장 중요한 규칙 — 원본 표기법 보존
**원본이 사용한 제시문 표기를 그대로 유지하세요.**
- 원본이 `[가]`, `[나]` 면 → `[가]`, `[나]`
- 원본이 `<제시문 1>`, `<제시문 2>` 면 → `<제시문 1>`, `<제시문 2>`
- 원본이 `(가)`, `(나)` 면 → `(가)`, `(나)`
- 원본이 `<자료 1>`, `<자료 2>` 면 → `<자료 1>`, `<자료 2>`
- **절대로 다른 형식으로 변환하지 말 것.** 제시문 참조도 원본 표기 그대로.

## 🔴 두 번째로 중요한 규칙 — 출처 정보는 원본에 있을 때만
**원본 텍스트에 출처(저자·책 제목·인용 표시)가 명시된 경우에만** `**출처**:` 줄을 작성하세요.
- 원본에 "-『고등학교 문학』" 같은 표시가 있으면 → `**출처**: 『고등학교 문학』`
- 원본에 "홍길동, 『책제목』" 같은 표시가 있으면 → `**출처**: 홍길동, 『책제목』`
- **원본에 출처 표시가 전혀 없으면 → `**출처**:` 줄 자체를 생략**
- **절대로 출처를 지어내거나 추측하지 말 것.** "성균관대학교 출제진", "재구성", "교과서 재구성" 같은 문구를 임의로 붙이지 말 것.

## 출력 규칙
1. 순수 Markdown 만 출력
2. YAML frontmatter 로 시작
3. **YAML 값에 쉼표·괄호가 있으면 반드시 큰따옴표로 감싸기** (예: track: "사회(통합사회, 사회문화)")
4. 제시문 원문은 한 글자도 빠짐없이 정확히
5. PDF 추출 과정의 줄바꿈 정리, 문단 전환만 빈 줄
6. 한자·외국어 그대로 유지

## 출력 형식

---
type: 논술기출매트릭스
university: (대학명 예: "성균관대학교")
university_short: (약칭 예: "성균관대")
year: (연도 숫자)
track: (계열명 · 쉼표·괄호 있으면 따옴표로 감싸기)
subtitle: (주제 요약, 없으면 빈 문자열)
exam_time: (시험시간 분, 숫자, 없으면 0)
problems_count: (문제 개수)
---

# 1부 · 문제

## [문제 1]

**지시문**: ※ 다음 제시문을 읽고 물음에 답하시오.

### 제시문

#### (원본 표기 그대로 · [가] 또는 <제시문 1> 등)
(원문 전체)

(원본에 출처 명시가 있는 경우에만) **출처**: 저자, 『교과서명』

#### (다음 제시문 표기)
...

### 문제
(논제 내용 · 제시문 참조도 원본 표기 그대로 · 배점 "(40점)" 은 그대로 유지)

(원본에 글자수·배점 조건이 별도 박스로 명시된 경우에만)
**조건**:
- 글자수: 400자 이내
- 배점: 40점

---

## [문제 2]
(동일 구조 반복)

## 주의사항
- 같은 지시문 아래 여러 문제가 있으면 제시문은 첫 번째 문제에만 포함
- 두 번째 문제부터는 "### 제시문" 섹션 생략하고 "### 문제" 바로 시작
- problems_count 는 실제 문제 개수
- 원본에 출처가 없으면 `**출처**:` 줄 자체를 생략 · 절대 지어내지 말 것
"""


SYSTEM_PART2_SINGLE_MD = """당신은 대학 논술 해설 텍스트를 Markdown 으로 변환하는 전문가입니다.

## 🔴 가장 중요한 규칙 — 원본 표기법 보존
해설에 나오는 제시문 참조는 **원본이 사용한 표기를 그대로 유지**하세요.
- 원본이 `[가]`, `[나]` 면 → 그대로
- 원본이 `<제시문 1>`, `<제시문 2>` 면 → 그대로
- 원본이 `(가)`, `(나)` 면 → 그대로
- **절대로 임의로 변환하지 말 것.**

## 출력 규칙
1. 순수 Markdown 만
2. YAML frontmatter 로 시작
3. 원문 한 글자도 빠짐없이 정확히
4. 한자·외국어 그대로 유지

## 출력 형식

---
problem_number: 1
---

## [문제 1] 해설

### 출제의도
(전체 텍스트 · 원본 표기 그대로)

### 문제해설
(전체 텍스트)

### 예시답안
(전체 텍스트)

### 채점기준
(채점 항목 텍스트 · 배점 포함)

### 채점등급표

| 등급 | 코드 | 기준 |
|------|------|------|
| 상 | A | ... |
| 중 | B | ... |
| 하 | C | ... |

## 채점등급표 변환 규칙
- 원본 A, B, C → "상" / D → "중" / E, F → "하" / S → "상"
- 등급표 없으면 ### 채점등급표 섹션 전체 생략
"""


# ────────────────────────────────────────────────────────────
# LLM 호출 (langchain 기반)
# ────────────────────────────────────────────────────────────

def call_gemini_md(system: str, user: str, label: str = "",
                   max_retries: int = 3) -> str | None:
    """Gemini 호출 → MD 텍스트 반환 · 429 재시도"""
    import time

    for attempt in range(1, max_retries + 1):
        try:
            llm = get_llm(provider="gemini", temperature=0.1)
            messages = [("system", system), ("human", user)]
            response = llm.invoke(messages)
            text = response.content if hasattr(response, "content") else str(response)

            text = _clean_md_wrapper(text)
            if label:
                print(f"  ✅ {label} MD 완료 ({len(text)}자)")
            return text

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                m = re.search(r"retry[^0-9]*(\d+(?:\.\d+)?)\s*s", err_str, re.IGNORECASE)
                wait_sec = float(m.group(1)) + 2 if m else 62
                wait_sec = min(wait_sec, 130)
                if attempt < max_retries:
                    print(f"  ⏳ {label} 429 rate limit — {wait_sec:.0f}초 대기 후 재시도...")
                    time.sleep(wait_sec)
                    continue
                else:
                    print(f"  ❌ {label} 재시도 초과 — 건너뜀")
                    return None
            else:
                print(f"  ⚠️ {label} 호출 실패: {e}")
                return None

    return None


def _clean_md_wrapper(text: str) -> str:
    """```md ... ``` 래퍼 제거"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    return text.strip()


# ────────────────────────────────────────────────────────────
# 메인 변환 로직
# ────────────────────────────────────────────────────────────

def convert_pdf_to_md(pdf_path: str, api_key: str = None) -> dict:
    """
    PDF → MD 변환.
    반환: {"full_md": str, "meta": dict, "problem_mds": [str, ...]}
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 필요")

    raw = extract_text(pdf_path)
    if len(raw.strip()) < 100:
        raise ValueError("텍스트 추출 실패 (스캔 PDF?)")

    structure = detect_structure(raw)
    print(f"🔍 PDF 구조 감지: [{structure}]")

    pdf_name = Path(pdf_path).name

    # ── [A] 문항카드형 ──────────────────────────────────────
    if structure == 'card':
        cards = split_card_sections(raw)
        print(f"📦 문항카드 {len(cards)}개 감지")

        problem_mds = []
        meta = None

        for i, card_text in enumerate(cards):
            label = f"문항카드 {i+1}"
            print(f"🤖 Gemini → MD ({label})...")

            md_text = call_gemini_md(
                SYSTEM_CARD_MD,
                f"아래 문항카드 텍스트를 Markdown 으로 변환하세요.\n"
                f"원문은 한 글자도 빠짐없이.\n\n"
                f"---\n{card_text}\n---",
                label
            )

            if md_text is None:
                print(f"  ⚠️ {label} 건너뜀")
                continue

            if meta is None:
                meta = _extract_meta_from_card(card_text, i + 1)

            problem_mds.append(md_text)

        if not meta:
            meta = _extract_meta_fallback(raw)
        if not problem_mds:
            raise RuntimeError("모든 문항카드 추출 실패")

        full_md = _assemble_card_md(meta, problem_mds, pdf_name)
        return {"full_md": full_md, "meta": meta, "problem_mds": problem_mds}

    # ── [B] 1부/2부 분리형 ──────────────────────────────────
    elif structure == 'split':
        part1_text, part2_text = split_parts(raw)

        print("🤖 Gemini → MD (1부 · 문제)...")
        part1_md = call_gemini_md(
            SYSTEM_PART1_MD,
            f"아래 텍스트를 Markdown 으로 변환하세요.\n\n---\n{part1_text}\n---",
            "1부"
        )
        if not part1_md:
            raise RuntimeError("1부 MD 추출 실패")

        meta = _parse_meta_from_md(part1_md) or _extract_meta_fallback(raw)

        part2_mds = []
        if part2_text:
            part2_chunks = split_part2_by_problem(part2_text)
            for i, chunk in enumerate(part2_chunks):
                label = f"2부 문제 {i+1}"
                print(f"🤖 Gemini → MD ({label})...")
                md = call_gemini_md(
                    SYSTEM_PART2_SINGLE_MD,
                    f"아래 해설을 Markdown 으로 변환하세요.\n\n---\n{chunk}\n---",
                    label
                )
                if md:
                    part2_mds.append(md)

        full_md = _assemble_split_md(meta, part1_md, part2_mds, pdf_name)
        return {"full_md": full_md, "meta": meta, "problem_mds": [part1_md] + part2_mds}

    # ── [C] 단순형 (문제만) ──────────────────────────────────
    else:
        print("🤖 Gemini → MD (단순형)...")
        md = call_gemini_md(
            SYSTEM_PART1_MD,
            f"아래 텍스트를 Markdown 으로 변환하세요.\n\n---\n{raw}\n---",
            "전체"
        )
        if not md:
            raise RuntimeError("MD 추출 실패")

        meta = _parse_meta_from_md(md) or _extract_meta_fallback(raw)
        full_md = _assemble_simple_md(meta, md, pdf_name)
        return {"full_md": full_md, "meta": meta, "problem_mds": [md]}


# ────────────────────────────────────────────────────────────
# MD 조립
# ────────────────────────────────────────────────────────────

def _build_frontmatter(meta: dict, pdf_name: str, problems_count: int) -> str:
    """YAML frontmatter 생성"""
    fm = {
        "type": "논술기출매트릭스",
        "university": meta.get("university", "대학명"),
        "university_short": meta.get("university_short") or _shorten_univ(meta.get("university", "")),
        "year": meta.get("year", 0),
        "track": meta.get("track", ""),
        "subtitle": meta.get("subtitle", ""),
        "exam_time": meta.get("examTime", meta.get("exam_time", 0)),
        "source_pdf": pdf_name,
        "problems_count": problems_count,
        "generated_by": "analy_engine",
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
    }
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, str) and (":" in v or "#" in v):
            v = f'"{v}"'
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _shorten_univ(name: str) -> str:
    """대학명 약칭 (성균관대학교 → 성균관대)"""
    if not name:
        return ""
    return name.replace("학교", "").strip()


def _assemble_card_md(meta: dict, problem_mds: list, pdf_name: str) -> str:
    """문항카드형 MD 조립"""
    fm = _build_frontmatter(meta, pdf_name, len(problem_mds))
    cleaned = [_strip_frontmatter(m) for m in problem_mds]

    parts = [fm, "", "# 1부 · 문제", ""]
    for md in cleaned:
        problem_part = _extract_problem_only(md)
        if problem_part:
            parts.append(problem_part)
            parts.append("")

    parts.extend(["---", "", "# 2부 · 해설", ""])
    for md in cleaned:
        solution_part = _extract_solution_only(md)
        if solution_part:
            parts.append(solution_part)
            parts.append("")

    return "\n".join(parts)


def _assemble_split_md(meta: dict, part1_md: str, part2_mds: list, pdf_name: str) -> str:
    """1부/2부 분리형 MD 조립"""
    fm = _build_frontmatter(meta, pdf_name, len(part2_mds) if part2_mds else 1)
    part1_cleaned = _strip_frontmatter(part1_md)
    part2_cleaned = [_strip_frontmatter(m) for m in part2_mds]

    parts = [fm, "", part1_cleaned]
    if part2_cleaned:
        parts.extend(["", "---", "", "# 2부 · 해설", ""])
        for md in part2_cleaned:
            parts.append(md)
            parts.append("")

    return "\n".join(parts)


def _assemble_simple_md(meta: dict, md: str, pdf_name: str) -> str:
    """단순형 MD 조립"""
    fm = _build_frontmatter(meta, pdf_name, 1)
    return "\n\n".join([fm, _strip_frontmatter(md)])


# ────────────────────────────────────────────────────────────
# MD 파싱 헬퍼
# ────────────────────────────────────────────────────────────

FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)


def _strip_frontmatter(md: str) -> str:
    """MD 에서 frontmatter 제거"""
    m = FRONTMATTER_RE.match(md)
    if m:
        return md[m.end():].strip()
    return md.strip()


def _parse_meta_from_md(md: str) -> dict | None:
    """MD frontmatter 에서 meta 추출"""
    m = FRONTMATTER_RE.match(md)
    if not m:
        return None
    meta = {}
    for line in m.group(1).split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v.isdigit():
                v = int(v)
            meta[k] = v
    return meta or None


def _extract_problem_only(md: str) -> str:
    """카드 MD 에서 문제 부분만 (## 해설 이전까지)"""
    parts = md.split("## 해설")
    return parts[0].strip()


def _extract_solution_only(md: str) -> str:
    """카드 MD 에서 해설 부분만 (문제 번호 헤더 포함)"""
    parts = md.split("## 해설", 1)
    if len(parts) < 2:
        return ""
    num_match = re.search(r'#\s*\[문제\s*(\d+)\]', parts[0])
    num = num_match.group(1) if num_match else "?"
    return f"## [문제 {num}]\n\n## 해설{parts[1].strip()}"


# ────────────────────────────────────────────────────────────
# CLI 테스트
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("사용법: python -m analy_engine.services.pdf_to_md <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    result = convert_pdf_to_md(pdf_path)
    print("\n" + "=" * 60)
    print("변환 완료!")
    print("=" * 60)
    print(result["full_md"][:2000])
    print("...")
    print(f"\n총 {len(result['full_md'])}자 · 문제 {len(result['problem_mds'])}개")

    out_path = Path(pdf_path).with_suffix(".md")
    out_path.write_text(result["full_md"], encoding="utf-8")
    print(f"💾 저장: {out_path}")

#!/usr/bin/env python3
"""
MD → JSON 변환 모듈 (v2)
==========================
실제 Gemini 출력 MD 구조에 맞춰 수정.
EOLE 매트릭스 포맷 MD 를 기존 JSON 스키마로 변환하여
generate_gyoan.js (DOCX 생성기) 를 재활용.

실제 MD 구조:
---
type: 논술기출매트릭스
university: ...
year: ...
track: ...
---

# 1부 · 문제
# [문제 1]
## 제시문
### [가]
(본문)
**출처**: ...
### [나]
...
## 문제
(논제)

# [문제 2]
...

# 2부 · 해설
## [문제 1]
## 해설### 출제의도   ← Gemini 가 종종 한 줄에 붙임
...
### 문제해설
### 예시답안
### 채점기준
### 채점등급표
"""
import re
import json
from pathlib import Path


# ────────────────────────────────────────────────────────────
# YAML frontmatter 파싱
# ────────────────────────────────────────────────────────────

FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


def parse_frontmatter(md: str) -> tuple[dict, str]:
    """MD 에서 frontmatter 추출"""
    # 개행 정규화
    md = md.replace('\r\n', '\n').replace('\r', '\n')

    m = FRONTMATTER_RE.match(md)
    if not m:
        return {}, md

    meta = {}
    for line in m.group(1).split("\n"):
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if v.isdigit():
            v = int(v)
        elif v.lower() in ("true", "false"):
            v = v.lower() == "true"
        meta[k] = v

    return meta, md[m.end():].strip()


# ────────────────────────────────────────────────────────────
# MD 전처리 - 깨진 헤더 수정
# ────────────────────────────────────────────────────────────

def preprocess_md(md: str) -> str:
    """Gemini 가 종종 만드는 파싱 방해 요소 수정"""
    # 개행 정규화
    md = md.replace('\r\n', '\n').replace('\r', '\n')

    # "## 해설### 출제의도" 같이 헤더가 붙어있는 경우 분리
    md = re.sub(r'(##\s*해설)(###)', r'\1\n\n\2', md)

    # 일반적으로 ## 헤더 뒤에 ### 이 바로 붙는 경우
    md = re.sub(r'(^##\s*[^\n]+)(###\s+)', r'\1\n\n\2', md, flags=re.MULTILINE)

    return md


# ────────────────────────────────────────────────────────────
# 섹션 분할
# ────────────────────────────────────────────────────────────

def split_into_parts(md: str) -> dict[str, str]:
    """
    MD 를 H1 로 분할.
    "# 1부 · 문제" 는 뒤에 여러 "# [문제 N]" 이 따라옴.
    "# 2부 · 해설" 아래에는 "## [문제 N]" 이 따라옴.
    """
    # "# 2부 · 해설" 로 분할
    part2_match = re.search(r'^#\s*2부.*?해설', md, flags=re.MULTILINE)

    if part2_match:
        part1_content = md[:part2_match.start()].strip()
        part2_content = md[part2_match.end():].strip()
    else:
        part1_content = md
        part2_content = ""

    return {"part1": part1_content, "part2": part2_content}


def split_problems_in_part1(part1_md: str) -> dict[int, str]:
    """
    1부에서 문제별 분할.
    패턴: "# [문제 N]" 또는 "## [문제 N]"
    """
    # "# [문제 N]" 또는 "## [문제 N]" 매치
    pattern = r'^#{1,3}\s*\[문제\s*(\d+)\]\s*$'
    parts = re.split(pattern, part1_md, flags=re.MULTILINE)

    result = {}
    for i in range(1, len(parts), 2):
        num = int(parts[i])
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        result[num] = body
    return result


def split_problems_in_part2(part2_md: str) -> dict[int, str]:
    """
    2부에서 문제별 분할.
    패턴: "## [문제 N]"
    """
    pattern = r'^##\s*\[문제\s*(\d+)\]\s*$'
    parts = re.split(pattern, part2_md, flags=re.MULTILINE)

    result = {}
    for i in range(1, len(parts), 2):
        num = int(parts[i])
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        result[num] = body
    return result


# ────────────────────────────────────────────────────────────
# 섹션 내용 추출 (유연한 헤더 레벨)
# ────────────────────────────────────────────────────────────

def extract_section_flexible(md: str, heading: str,
                              min_level: int = 2, max_level: int = 4) -> str:
    """
    특정 heading 의 내용 추출. 헤더 레벨 유연 (## 부터 #### 까지 시도).
    다음 같은/상위 레벨 헤더까지.
    """
    for level in range(min_level, max_level + 1):
        h = "#" * level
        pattern = rf'^{h}\s*{re.escape(heading)}\s*$\n'
        m = re.search(pattern, md, flags=re.MULTILINE)
        if not m:
            continue

        start = m.end()
        # 다음 같은 또는 상위 레벨 헤더
        next_pattern = rf'^#{{1,{level}}}\s+'
        next_m = re.search(next_pattern, md[start:], flags=re.MULTILINE)
        end = start + next_m.start() if next_m else len(md)

        return md[start:end].strip()

    return ""


def parse_passages_flexible(part1_problem_body: str) -> list[dict]:
    """
    1부 문제 본문에서 제시문 파싱.
    실제 구조: ## 제시문 다음에 ### [가], ### [나], ...
    """
    # "## 제시문" 섹션 찾기
    passages_section = extract_section_flexible(
        part1_problem_body, "제시문", min_level=2, max_level=3
    )

    if not passages_section:
        return []

    # ### [라벨] 또는 #### [라벨] 으로 분할
    # 라벨은 [가], [나], ... 또는 <제시문 1>, <자료 1> 등 다양
    pattern = r'^(?:###|####)\s*(\[[^\]]+\]|<[^>]+>|\([^)]+\))\s*$'
    parts = re.split(pattern, passages_section, flags=re.MULTILINE)

    passages = []
    for i in range(1, len(parts), 2):
        label = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""

        text, source, textbook = _split_passage_body(body)

        passages.append({
            "label": label,
            "text": text,
            "source": source,
            "textbook": textbook,
        })

    return passages


def _split_passage_body(body: str) -> tuple[str, str, str]:
    """제시문 본문에서 출처 / 교과서명 추출"""
    source_match = re.search(r'\*\*출처\*\*:?\s*(.+?)(?:\n|$)', body)
    if not source_match:
        return body.strip(), "", ""

    source_line = source_match.group(1).strip()
    text = body[:source_match.start()].strip()

    # 교과서명 『...』 추출
    textbook = ""
    tb_match = re.search(r'『([^』]+)』', source_line)
    if tb_match:
        textbook = f"『{tb_match.group(1)}』"
        source = source_line.replace(textbook, "").strip().rstrip(",").strip()
    else:
        source = source_line

    return text, source, textbook


def parse_question_flexible(part1_problem_body: str) -> dict:
    """
    "## 문제" 섹션 파싱. 실제 구조: ## 문제 아래에 논제 본문.
    본문에서 배점/글자수를 추출한 후 본문에서 제거하여 렌더러 중복 출력 방지.
    """
    question_md = extract_section_flexible(
        part1_problem_body, "문제", min_level=2, max_level=3
    )
    if not question_md:
        return {"text": "", "wordCount": "", "points": 0}

    text = question_md
    word_count = ""
    points = 0

    # **조건** 블록이 있으면 먼저 추출 및 제거
    cond_match = re.search(r'\*\*조건\*\*:?\s*\n((?:-[^\n]*\n?)+)', text)
    if cond_match:
        cond_block = cond_match.group(1)

        wc_m = re.search(r'글자수:\s*([^\n]+)', cond_block)
        if wc_m:
            word_count = wc_m.group(1).strip()

        pt_m = re.search(r'배점:\s*(\d+)', cond_block)
        if pt_m:
            points = int(pt_m.group(1))

        # 본문에서 조건 블록 제거
        text = text[:cond_match.start()].strip()

    # 본문에 "(40점)" 같은 형태로 배점이 있으면 → points 필드로 저장 후 본문에서 제거
    pt_inline = re.search(r'\s*\((\d+)\s*점\)', text)
    if pt_inline:
        if points == 0:  # 조건 블록에 없었으면 여기서 추출
            points = int(pt_inline.group(1))
        # 본문에서 "(40점)" 제거하여 렌더러 중복 방지
        text = text[:pt_inline.start()].rstrip() + text[pt_inline.end():]
        text = text.strip()

    # 본문에 글자수가 있으면 → wordCount 필드로 저장 후 본문에서 제거
    wc_inline = re.search(r'\s*\((\d+(?:\s*[~-]\s*\d+)?\s*자(?:\s*(?:이내|내외|내))?)\)', text)
    if wc_inline:
        if not word_count:  # 조건 블록에 없었으면
            word_count = wc_inline.group(1).strip()
        text = text[:wc_inline.start()].rstrip() + text[wc_inline.end():]
        text = text.strip()
    elif not word_count:
        # 괄호 없이 본문에 글자수만 있는 경우 (추출만, 제거는 안 함)
        wc_plain = re.search(r'(\d+(?:\s*[~-]\s*\d+)?\s*자(?:\s*(?:이내|내외|내))?)', text)
        if wc_plain:
            word_count = wc_plain.group(1)

    return {
        "text": text.strip(),
        "wordCount": word_count,
        "points": points,
    }


def parse_instructions(part1_problem_body: str) -> str:
    """지시문 추출"""
    m = re.search(r'\*\*지시문\*\*:?\s*([^\n]+)', part1_problem_body)
    return m.group(1).strip() if m else ""


# ────────────────────────────────────────────────────────────
# 2부 해설 파싱
# ────────────────────────────────────────────────────────────

def parse_solution_body(part2_problem_body: str) -> dict:
    """2부 문제 해설 파싱"""
    return {
        "출제의도": extract_section_flexible(
            part2_problem_body, "출제의도", min_level=3, max_level=4
        ),
        "문제해설": extract_section_flexible(
            part2_problem_body, "문제해설", min_level=3, max_level=4
        ),
        "sampleAnswer": extract_section_flexible(
            part2_problem_body, "예시답안", min_level=3, max_level=4
        ),
        "rubric": extract_section_flexible(
            part2_problem_body, "채점기준", min_level=3, max_level=4
        ),
        "rubricTable": parse_rubric_table(
            extract_section_flexible(
                part2_problem_body, "채점등급표", min_level=3, max_level=4
            )
        ),
    }


def parse_rubric_table(rubric_md: str) -> list[dict]:
    """채점등급표 MD 테이블 파싱"""
    if not rubric_md:
        return []

    rows = []
    in_body = False
    for line in rubric_md.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not cells:
            continue
        # 구분선 스킵
        if all(re.match(r'^-+$', c) for c in cells):
            in_body = True
            continue
        if not in_body:
            continue  # 헤더 스킵
        if len(cells) >= 3:
            rows.append({
                "grade": cells[0],
                "code": cells[1],
                "desc": cells[2],
            })

    return rows


def build_commentary(passages: list[dict]) -> list[dict]:
    """passages 기반 commentary 자동 생성"""
    result = []
    for p in passages:
        parts = [p.get("text", "")]
        if p.get("source"):
            parts.append(p["source"])
        if p.get("textbook"):
            parts.append(f"-{p['textbook']}")
        result.append({"label": p.get("label", ""), "text": "\n".join(parts)})
    return result


# ────────────────────────────────────────────────────────────
# 메인 변환
# ────────────────────────────────────────────────────────────

def md_to_json(md: str) -> dict:
    """EOLE 매트릭스 MD → 기존 JSON 스키마 변환"""
    # 1. frontmatter
    meta_fm, body = parse_frontmatter(md)

    # 2. 전처리
    body = preprocess_md(body)

    # 3. meta
    meta = {
        "university": meta_fm.get("university", ""),
        "year": meta_fm.get("year", 0),
        "track": meta_fm.get("track", ""),
        "subtitle": meta_fm.get("subtitle", ""),
        "examTime": meta_fm.get("exam_time", 0),
    }

    # 4. 1부 / 2부 분할
    parts = split_into_parts(body)

    # 5. 1부 문제들
    problems_part1 = split_problems_in_part1(parts["part1"])

    # 6. 2부 해설들
    problems_part2 = split_problems_in_part2(parts["part2"]) if parts["part2"] else {}

    # 7. 문제별 조립
    problem_sets_map = {}
    all_numbers = set(problems_part1.keys()) | set(problems_part2.keys())

    for num in all_numbers:
        ps = {
            "number": num,
            "instructions": "",
            "passages": [],
            "question": {"text": "", "wordCount": "", "points": 0},
        }

        # 1부 파싱
        if num in problems_part1:
            p1_body = problems_part1[num]
            ps["instructions"] = parse_instructions(p1_body)
            ps["passages"] = parse_passages_flexible(p1_body)
            ps["question"] = parse_question_flexible(p1_body)

        # 2부 파싱 (해설)
        if num in problems_part2:
            p2_body = problems_part2[num]
            ps.update(parse_solution_body(p2_body))

        _fill_defaults(ps)
        problem_sets_map[num] = ps

    # 8. 번호 순 정렬
    problem_sets = [problem_sets_map[n] for n in sorted(problem_sets_map.keys())]

    return {"meta": meta, "problemSets": problem_sets}


def _fill_defaults(ps: dict) -> dict:
    """problemSet 에 누락 필드 기본값"""
    defaults = {
        "instructions": "",
        "passages": [],
        "question": {"text": "", "wordCount": "", "points": 0},
        "출제의도": "",
        "문제해설": "",
        "sampleAnswer": "",
        "rubric": "",
        "rubricTable": [],
    }
    for k, v in defaults.items():
        if k not in ps or ps[k] is None:
            ps[k] = v

    if not ps.get("commentary"):
        ps["commentary"] = build_commentary(ps.get("passages", []))

    return ps


# ────────────────────────────────────────────────────────────
# CLI 테스트
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("사용법: python -m analy_engine.services.md_to_json <md_path>")
        sys.exit(1)

    md_path = sys.argv[1]
    md = Path(md_path).read_text(encoding="utf-8")
    result = md_to_json(md)

    out_path = Path(md_path).with_suffix(".json")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 변환 완료: {out_path}")
    print(f"   · 대학: {result['meta'].get('university')}")
    print(f"   · 문제 수: {len(result['problemSets'])}")
    for ps in result['problemSets']:
        print(f"   · 문제 {ps['number']}: 제시문 {len(ps['passages'])}개, "
              f"출제의도 {len(ps.get('출제의도', ''))}자, "
              f"예시답안 {len(ps.get('sampleAnswer', ''))}자, "
              f"채점등급표 {len(ps.get('rubricTable', []))}행")

"""
논술 첨삭 에이전트
목표 출력: 문장 번호 부여 원문 + 장점/단점/보완할 부분/총평

LLM 우선순위:
  1. LLM_PROVIDER=ollama  → Ollama 로컬 (Gemma 3 등)
  2. GEMINI_API_KEY 있음  → Gemini API
  3. 그 외               → OpenAI GPT-4o
"""
import os
import re
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


def _get_llm():
    from eval_engine.services.crud import get_llm_provider, get_ollama_model, get_gemini_model
    provider = get_llm_provider().lower()

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=get_ollama_model(), temperature=0.1)

    if os.getenv("GEMINI_API_KEY"):
        return ChatGoogleGenerativeAI(
            model=get_gemini_model(),
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=0.1,
        )

    return ChatOpenAI(model="gpt-4o", temperature=0.1)


def build_annotation_prompt(
    ocr_text: str,
    problem: dict | None,
    system_prompt_content: str,
    item_number: int = 1,
) -> tuple[str, str]:

    if problem:
        context = f"""[문제]
{problem.get('question', '')}

[제시문]
{problem.get('passages', '') or '제시문 없음'}

[예시 답안]
{problem.get('sample_answer', '') or '예시 답안 없음'}

[채점 기준]
{problem.get('scoring_criteria', '') or '채점 기준 없음'}"""
    else:
        context = "(문제 정보 없음 — 답안 내용만으로 평가)"

    user_prompt = f"""{context}

[학생 답안 — 문항 {item_number}번]
{ocr_text}

위 학생 답안을 시스템 지침에 따라 평가하세요.
반드시 아래 형식을 정확히 지켜 출력하세요. 각 섹션 태그(===)는 반드시 포함해야 합니다.

===원문===
(아래 규칙을 반드시 지켜 출력:
1. 번호(❶❷❸)는 반드시 각 문장의 맨 앞에 붙인다. 번호는 문장 바로 앞에 붙여쓰기
2. 같은 문단 내 문장들은 줄바꿈 없이 이어서 출력. 문단이 바뀔 때만 줄바꿈
3. 원문 글자 하나도 수정 금지 (오탈자 포함)
4. 마지막에 "총 XXX자" 표시
올바른 예: ❶첫 번째 문장이다. ❷두 번째 문장이다. ❸세 번째 문장이다.
잘못된 예: 첫 번째 문장이다.❶ 두 번째 문장이다.❷)
===장점===
(학생이 잘 한 점 2~4문장. 어조: 존댓말. 주어: 학생.
금지: '지도해야 합니다', '향상시켜야 합니다' 등 교사 입장 표현)
===단점===
(핵심 논거 누락, 독해 오류, 논리적 비약 등 2~4문장. 어조: 존댓말. 주어: 학생.
금지: '지도가 필요합니다', '훈련해야 합니다' 등 교사 입장 표현)
===보완할 부분===
[형식 규칙 — 반드시 준수]
각 항목은 정확히 4줄 구조입니다.
1줄: (번호) ❶번 문장 — 문제점 요약 한 문장  ← 원문/수정문 절대 포함 금지
2줄: 수정 전: 학생 원문 그대로
3줄: 수정 후: 개선된 문장
4줄: → 수정 이유: 설명

[올바른 예]
(1) ❸번 문장 — 논리적 근거 없이 결론을 단정짓고 있습니다.
수정 전: 따라서 (가)의 입장을 부정적으로 평가할 수 있다.
수정 후: (가)는 재분배 범위를 간과한다는 점에서 한계가 있습니다.
→ 수정 이유: 단정적 표현 대신 구체적 근거를 제시하여 논리적 설득력을 높입니다.

[잘못된 예 — 절대 금지]
(1) ❸번 문장 — "따라서 (가)의 입장을 부정적으로 평가할 수 있다." → "개선된 문장" → 이유
← 헤더에 원문과 수정문을 → 기호로 나열하는 방식은 절대 금지

(항목 수는 실제 수정 필요한 문장 수에 맞게, 최대 5개)
===총평===
(구조적 완성도, 논리의 깊이, 향후 방향 3~5문장. 어조: 존댓말. 주어: 학생.
금지: '지도하겠습니다', '훈련이 필요합니다', '함께 노력합시다')
===점수===
(0~100 사이 숫자만)"""

    # 한국어 전용 지시 — Gemini의 다국어 토큰 오염 방지
    korean_guard = (
        "\n\n[언어 규칙] 반드시 한국어로만 응답하세요. "
        "영어, 스페인어, 일본어 등 다른 언어 단어가 절대 섞이면 안 됩니다. "
        "모든 전문 용어도 반드시 한국어로만 표기하세요."
    )
    enforced_system = system_prompt_content + korean_guard

    return enforced_system, user_prompt


def _clean(text: str) -> str:
    text = re.sub(r'\*{2}([^*]+)\*{2}', r'\1', text)
    text = text.replace('**', '')
    text = re.sub(r'\*([^*\n]+)\*', r'\1', text)
    text = text.replace('*', '')
    text = re.sub(r'_{2}([^_]+)_{2}', r'\1', text)
    lines = text.split('\n')
    lines = [l.lstrip('# ') if l.startswith('#') else l for l in lines]
    text = '\n'.join(lines)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\s*\([가-힣]+체\s*[가-힣]*\)\s*', ' ', text)
    text = text.strip()
    if text.startswith('(') and text.endswith(')'):
        inner = text[1:-1].strip()
        if inner.count('(') == inner.count(')'):
            text = inner
    return text.strip()


def _fmt_improvements(text: str) -> str:
    parts = text.split('\n\n')
    cur, items = '', []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if re.match(r'^\(\d+\)', p):
            if cur.strip():
                items.append(cur.strip())
            cur = p
        else:
            cur += '\n' + p if cur else p
    if cur.strip():
        items.append(cur.strip())
    if not items:
        return text
    result = []
    for item in items:
        ls = item.split('\n')
        header, body = ls[0], '\n'.join(ls[1:])
        body = re.sub(r'\s*수정\s*전:\s*', '\n수정 전: ', body)
        body = re.sub(r'\s*수정\s*후:\s*', '\n수정 후: ', body)
        body = re.sub(r'\s*→\s*수정\s*이유:\s*', '\n→ 수정 이유: ', body)
        result.append(header + body)
    return '\n\n'.join(result)


def parse_annotation_response(raw: str) -> dict:
    sections = {
        "numbered_text": "", "strengths": "", "weaknesses": "",
        "improvements": "", "summary": "", "score": None,
        "char_count": 0, "raw": raw,
    }
    patterns = [
        ("numbered_text", r"===원문===(.*?)===장점==="),
        ("strengths",     r"===장점===(.*?)===단점==="),
        ("weaknesses",    r"===단점===(.*?)===보완할 부분==="),
        ("improvements",  r"===보완할 부분===(.*?)===총평==="),
        ("summary",       r"===총평===(.*?)===점수==="),
        ("score_raw",     r"===점수===(.*?)$"),
    ]
    for key, pattern in patterns:
        m = re.search(pattern, raw, re.DOTALL)
        if m:
            val = m.group(1).strip()
            if key == "score_raw":
                nums = re.findall(r"\d+(?:\.\d+)?", val)
                if nums:
                    sections["score"] = float(nums[0])
            else:
                cleaned = _clean(val)
                if key == "improvements":
                    cleaned = _fmt_improvements(cleaned)
                sections[key] = cleaned
    m2 = re.search(r"(\d+)\s*자", sections["numbered_text"])
    if m2:
        sections["char_count"] = int(m2.group(1))
    return sections


def annotate_item(
    ocr_text: str,
    problem: dict | None,
    system_prompt_content: str,
    item_number: int = 1,
) -> dict:
    system_p, user_p = build_annotation_prompt(
        ocr_text, problem, system_prompt_content, item_number
    )
    llm = _get_llm()
    messages = [("system", system_p), ("human", user_p)]
    response = llm.invoke(messages)
    raw = response.content if hasattr(response, "content") else str(response)
    return parse_annotation_response(raw)

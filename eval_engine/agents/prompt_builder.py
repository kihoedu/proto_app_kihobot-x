"""
평가 프롬프트 빌더
논술 문제의 기초자료(문제/제시문/예시답안/채점기준)를 프롬프트에 주입
"""

# ── 기본 평가 프롬프트 양식 ───────────────────────────────────
# 문제별 prompt_template 이 있으면 그것을, 없으면 이 기본 양식을 사용
DEFAULT_EVAL_TEMPLATE = """당신은 논술 채점 전문가입니다. 아래 자료를 바탕으로 학생 답안의 [{dimension}] 영역을 채점하세요.

## 문제
{question}

## 제시문
{passages}

## 예시 답안 (참고용)
{sample_answer}

## 채점 기준
{scoring_criteria}

## 유사 답안 참고 사례
{similar_examples}

## 학생 답안
{student_answer}

---
위 자료를 바탕으로 [{dimension}] 영역을 엄격하고 공정하게 채점하세요.
최대 배점: {max_score}점

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 금지):
{{
  "score": <0~{max_score} 숫자>,
  "confidence": <0.0~1.0 확신도>,
  "strengths": ["강점1", "강점2"],
  "weaknesses": ["약점1", "약점2"],
  "feedback": "2~3문장 구체적 피드백"
}}"""


DEFAULT_SYSTEM_PROMPT = """당신은 대학 입시 논술을 전문적으로 채점하는 채점관입니다.
- 채점 기준을 엄격히 적용하되 학생의 노력을 공정하게 평가합니다
- 예시 답안과 비교하여 수준을 가늠하되, 동일한 논지라도 독창적 표현은 긍정 평가합니다
- 반드시 JSON 형식으로만 응답합니다"""


DIM_NAMES = {
    "logic":       "논리·논증력",
    "content":     "내용·이해도",
    "expression":  "표현·문체",
    "fact_check":  "사실·근거",
    "creativity":  "창의성",
}

DEFAULT_SCORE_WEIGHTS = {
    "logic": 25, "content": 30, "expression": 20,
    "fact_check": 15, "creativity": 10,
}


def build_eval_prompt(
    dimension: str,
    student_answer: str,
    problem: dict | None,
    similar_examples: list[dict],
    max_score: int,
    system_prompt_content: str | None = None,
) -> tuple[str, str]:
    """
    (system_prompt, user_prompt) 튜플 반환.
    system_prompt_content: DB에서 가져온 공통 프롬프트 (없으면 DEFAULT_SYSTEM_PROMPT 사용)
    problem 이 None 이면 학생 답안만으로 평가 (fallback).
    """
    # 공통 시스템 프롬프트 결정
    sys_prompt = system_prompt_content or DEFAULT_SYSTEM_PROMPT

    dim_label = DIM_NAMES.get(dimension, dimension)
    similar_text = "\n\n".join(
        f"[사례{i+1}] 점수:{ex['score']} | {ex['feedback']}"
        for i, ex in enumerate(similar_examples)
    ) or "참고 사례 없음"

    if problem is None:
        user_prompt = f"""학생 답안을 [{dim_label}] 관점에서 채점하세요. (최대 {max_score}점)

## 유사 사례
{similar_text}

## 학생 답안
{student_answer[:3000]}

JSON 형식으로만 응답:
{{"score":<점수>,"confidence":<0~1>,"strengths":[],"weaknesses":[],"feedback":""}}"""
        return sys_prompt, user_prompt

    # 문제별 커스텀 템플릿 or 기본 템플릿
    template = problem.get("prompt_template") or DEFAULT_EVAL_TEMPLATE

    user_prompt = template.format(
        dimension       = dim_label,
        question        = problem.get("question", ""),
        passages        = problem.get("passages", "") or "제시문 없음",
        sample_answer   = problem.get("sample_answer", "") or "예시 답안 없음",
        scoring_criteria= problem.get("scoring_criteria", "") or "채점 기준 없음",
        similar_examples= similar_text,
        student_answer  = student_answer[:3000],
        max_score       = max_score,
    )

    return sys_prompt, user_prompt


def get_score_weights(problem: dict | None) -> dict:
    """문제별 배점 반환. 없으면 기본값."""
    if problem and problem.get("score_weights"):
        w = problem["score_weights"]
        if all(k in w for k in DEFAULT_SCORE_WEIGHTS):
            return w
    return DEFAULT_SCORE_WEIGHTS.copy()

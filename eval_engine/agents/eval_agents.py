import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from eval_engine.services.schemas import EssayEvalState, DimensionScore, AgentScores
from eval_engine.agents.rag_store import get_similar_essays
from eval_engine.agents.prompt_builder import build_eval_prompt, get_score_weights


def _get_llm():
    if os.getenv("GEMINI_API_KEY"):
        return ChatGoogleGenerativeAI(
            model="gemini-1.5-pro",
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=0.2,
        )
    return ChatOpenAI(model="gpt-4o", temperature=0.2)


def _run_dimension(dimension: str, essay_text: str,
                   problem: dict | None, score_weights: dict,
                   system_prompt_content: str | None = None) -> DimensionScore:
    max_score = score_weights.get(dimension, 20)
    similar   = get_similar_essays(essay_text, dimension, k=2)

    system_p, user_p = build_eval_prompt(
        dimension=dimension, student_answer=essay_text,
        problem=problem, similar_examples=similar, max_score=max_score,
        system_prompt_content=system_prompt_content,
    )
    llm    = _get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_p),
        ("human",  "{user_prompt}"),
    ])
    result = (prompt | llm | JsonOutputParser()).invoke({"user_prompt": user_p})

    return DimensionScore(
        score      = min(float(result.get("score", 0)), max_score),
        max_score  = float(max_score),
        confidence = float(result.get("confidence", 0.7)),
        strengths  = result.get("strengths", []),
        weaknesses = result.get("weaknesses", []),
        feedback   = result.get("feedback", ""),
    )


def evaluation_node_dict(state: dict) -> dict:
    s = EssayEvalState(**state)
    if not s.ocr_text:
        s.error = "OCR 텍스트가 없습니다."
        return s.model_dump()

    # 문제 기초자료 + 공통 시스템 프롬프트 로드
    problem = None
    system_prompt_content = None
    if s.problem_id:
        from eval_engine.services.crud import get_problem, resolve_system_prompt_for_problem
        problem = get_problem(s.problem_id)
        system_prompt_content = resolve_system_prompt_for_problem(problem)

    score_weights = get_score_weights(problem)
    scores: dict  = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_run_dimension, dim, s.ocr_text, problem,
                           score_weights, system_prompt_content): dim
            for dim in score_weights
        }
        for future in as_completed(futures):
            dim = futures[future]
            try:
                scores[dim] = future.result()
            except Exception as e:
                scores[dim] = DimensionScore(
                    score=0, max_score=score_weights.get(dim, 20),
                    confidence=0.0, feedback=f"평가 오류: {e}"
                )

    s.agent_scores = AgentScores(
        logic      = scores.get("logic"),
        content    = scores.get("content"),
        expression = scores.get("expression"),
        fact_check = scores.get("fact_check"),
        creativity = scores.get("creativity"),
    )
    return s.model_dump()

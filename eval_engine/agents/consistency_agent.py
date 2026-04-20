import statistics
from datetime import datetime
from eval_engine.services.schemas import (
    EssayEvalState, ConsistencyResult, EvaluationReport,
    EvalStatus, AgentScores
)
from eval_engine.services.config import DEFAULT_CRITERIA, CONSISTENCY_THRESHOLDS


def consistency_node_dict(state: dict) -> dict:
    """점수 일관성 검증: 분산·신뢰도 체크"""
    s = EssayEvalState(**state)
    scores_obj = s.agent_scores
    criteria = s.criteria or DEFAULT_CRITERIA
    dims = criteria["dimensions"]

    # 정규화된 점수(0~100) 수집
    norm_scores = []
    low_conf_dims = []

    for dim_key, dim_cfg in dims.items():
        dim_score = getattr(scores_obj, dim_key, None)
        if dim_score is None:
            continue
        normalized = (dim_score.score / dim_cfg["max_score"]) * 100
        norm_scores.append(normalized)
        if dim_score.confidence < CONSISTENCY_THRESHOLDS["min_confidence"]:
            low_conf_dims.append(dim_key)

    variance = statistics.variance(norm_scores) if len(norm_scores) > 1 else 0.0
    needs_retry = (
        variance > CONSISTENCY_THRESHOLDS["max_variance"]
        or len(low_conf_dims) >= 2
    ) and s.retry_count < CONSISTENCY_THRESHOLDS["max_retries"]

    s.consistency = ConsistencyResult(
        passed=not needs_retry,
        score_variance=round(variance, 2),
        low_confidence_dims=low_conf_dims,
        needs_retry=needs_retry,
        retry_reason=(
            f"점수 분산 {variance:.1f} > {CONSISTENCY_THRESHOLDS['max_variance']}"
            if variance > CONSISTENCY_THRESHOLDS["max_variance"]
            else f"낮은 신뢰도 항목: {', '.join(low_conf_dims)}"
        ) if needs_retry else "",
    )

    if needs_retry:
        s.retry_count += 1

    return s.model_dump()


def finalize_node_dict(state: dict) -> dict:
    """최종 점수 산출 및 리포트 생성"""
    s = EssayEvalState(**state)
    criteria = s.criteria or DEFAULT_CRITERIA
    dims = criteria["dimensions"]
    scores_obj = s.agent_scores

    # 가중 합산
    total = 0.0
    for dim_key, dim_cfg in dims.items():
        dim_score = getattr(scores_obj, dim_key, None)
        if dim_score:
            total += dim_score.score  # max_score가 이미 weight 반영됨

    # 등급 산출
    grade = "F"
    for g, (lo, hi) in criteria["grade_scale"].items():
        if lo <= total <= hi:
            grade = g
            break

    # 개선 포인트 수집
    improvement_points = []
    for dim_key in dims:
        dim_score = getattr(scores_obj, dim_key, None)
        if dim_score and dim_score.weaknesses:
            improvement_points.extend(dim_score.weaknesses[:1])

    # 종합 피드백
    summary = _generate_summary(total, grade, scores_obj)

    now = datetime.now().isoformat()
    s.final_report = EvaluationReport(
        submission_id=s.submission_id,
        student_id=s.student_id,
        ocr_text=s.ocr_text,
        ocr_confidence=s.ocr_confidence,
        agent_scores=scores_obj,
        consistency=s.consistency,
        final_score=round(total, 1),
        final_grade=grade,
        summary_feedback=summary,
        improvement_points=improvement_points,
        status=EvalStatus.DONE,
        retry_count=s.retry_count,
        created_at=now,
        updated_at=now,
    )
    return s.model_dump()


def _generate_summary(score: float, grade: str, scores: AgentScores) -> str:
    dim_names = {
        "logic": "논리력", "content": "내용", "expression": "표현",
        "fact_check": "사실성", "creativity": "창의성"
    }
    top_dims = []
    weak_dims = []
    for key, name in dim_names.items():
        dim = getattr(scores, key, None)
        if not dim:
            continue
        ratio = dim.score / dim.max_score
        if ratio >= 0.8:
            top_dims.append(name)
        elif ratio < 0.6:
            weak_dims.append(name)

    parts = [f"총점 {score:.1f}점 ({grade}등급)."]
    if top_dims:
        parts.append(f"{', '.join(top_dims)} 영역이 우수합니다.")
    if weak_dims:
        parts.append(f"{', '.join(weak_dims)} 영역의 보완이 필요합니다.")
    return " ".join(parts)


# ── LangGraph 라우터 ─────────────────────────────────────────
def route_after_consistency(state: dict) -> str:
    s = EssayEvalState(**state)
    if s.consistency and s.consistency.needs_retry:
        return "re_evaluate"
    return "finalize"

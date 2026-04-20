from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class EvalStatus(str, Enum):
    PENDING = "pending"
    OCR_DONE = "ocr_done"
    EVALUATING = "evaluating"
    CONSISTENCY_CHECK = "consistency_check"
    DONE = "done"
    NEEDS_REVIEW = "needs_review"
    TEACHER_REVIEWED = "teacher_reviewed"


class DimensionScore(BaseModel):
    score: float = Field(..., ge=0, le=100)
    max_score: float = 100.0
    confidence: float = Field(..., ge=0.0, le=1.0, description="0~1, 에이전트 확신도")
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    feedback: str = ""


class AgentScores(BaseModel):
    logic: Optional[DimensionScore] = None        # 논리·논증
    content: Optional[DimensionScore] = None      # 내용·이해
    expression: Optional[DimensionScore] = None   # 표현·문체
    fact_check: Optional[DimensionScore] = None   # 사실·근거
    creativity: Optional[DimensionScore] = None   # 창의성


class ConsistencyResult(BaseModel):
    passed: bool
    score_variance: float
    low_confidence_dims: list[str] = Field(default_factory=list)
    needs_retry: bool = False
    retry_reason: str = ""


class TeacherFeedback(BaseModel):
    teacher_id: str = "teacher_01"
    adjusted_scores: dict[str, float] = Field(default_factory=dict)
    overall_comment: str = ""
    dimension_comments: dict[str, str] = Field(default_factory=dict)
    approved: bool = False
    reviewed_at: Optional[str] = None


class EvaluationReport(BaseModel):
    submission_id: str
    student_id: str = "unknown"
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    agent_scores: AgentScores = Field(default_factory=AgentScores)
    consistency: Optional[ConsistencyResult] = None
    final_score: float = 0.0
    final_grade: str = ""
    summary_feedback: str = ""
    improvement_points: list[str] = Field(default_factory=list)
    status: EvalStatus = EvalStatus.PENDING
    retry_count: int = 0
    teacher_feedback: Optional[TeacherFeedback] = None
    created_at: str = ""
    updated_at: str = ""


class EssayEvalState(BaseModel):
    """LangGraph 상태 객체"""
    submission_id: str
    student_id: str
    image_paths: list[str]           # 업로드된 이미지/PDF 경로
    problem_id: Optional[str] = None # 논술 문제 ID → DB에서 기초자료 로드
    criteria: dict = {}              # fallback 채점 기준
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    agent_scores: AgentScores = Field(default_factory=AgentScores)
    consistency: Optional[ConsistencyResult] = None
    final_report: Optional[EvaluationReport] = None
    retry_count: int = 0
    error: str = ""

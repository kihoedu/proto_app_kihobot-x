import os, json
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Float, Integer,
    Text, Boolean, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/essay_eval.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class SystemPromptORM(Base):
    """공통 시스템 프롬프트 — 역할 설정 / 출력 형식 / 평가 원칙"""
    __tablename__ = "system_prompts"
    prompt_id   = Column(String(32), primary_key=True)
    name        = Column(String(128), nullable=False)
    description = Column(Text, default="")
    content     = Column(Text, nullable=False)
    is_default  = Column(Boolean, default=False)
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    problems    = relationship("EssayProblemORM", back_populates="system_prompt")

    def to_dict(self):
        return {
            "prompt_id": self.prompt_id, "name": self.name,
            "description": self.description, "content": self.content,
            "is_default": self.is_default, "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class EssayProblemORM(Base):
    """논술 문제 마스터 — 문제/제시문/예시답안/채점기준/프롬프트"""
    __tablename__ = "essay_problems"
    problem_id       = Column(String(32), primary_key=True)
    title            = Column(String(256), nullable=False)
    subject          = Column(String(64),  default="")
    year             = Column(String(8),   default="")
    university       = Column(String(64),  default="")
    time_limit       = Column(Integer,     default=0)
    question         = Column(Text, nullable=False)
    passages         = Column(Text, default="")
    sample_answer    = Column(Text, default="")
    scoring_criteria = Column(Text, default="")
    prompt_template  = Column(Text, default="")
    score_weights_json = Column(Text, default="{}")
    system_prompt_id = Column(String(32), ForeignKey("system_prompts.prompt_id"), nullable=True)
    active     = Column(Boolean,  default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submissions   = relationship("SubmissionORM", back_populates="problem")
    system_prompt = relationship("SystemPromptORM", back_populates="problems")

    @property
    def score_weights(self):
        return json.loads(self.score_weights_json or "{}")
    @score_weights.setter
    def score_weights(self, v):
        self.score_weights_json = json.dumps(v, ensure_ascii=False)

    def to_dict(self):
        return {
            "problem_id": self.problem_id, "title": self.title,
            "subject": self.subject, "year": self.year,
            "university": self.university, "time_limit": self.time_limit,
            "question": self.question, "passages": self.passages,
            "sample_answer": self.sample_answer,
            "scoring_criteria": self.scoring_criteria,
            "prompt_template": self.prompt_template,
            "score_weights": self.score_weights,
            "system_prompt_id": self.system_prompt_id,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class StudentORM(Base):
    __tablename__ = "students"
    student_id  = Column(String(64), primary_key=True)
    name        = Column(String(128), default="")
    grade       = Column(String(16),  default="")
    class_name  = Column(String(32),  default="")
    note        = Column(Text, default="")
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submissions = relationship("SubmissionORM", back_populates="student",
                               cascade="all, delete-orphan")


class SubmissionORM(Base):
    """제출 단위 — 학생 한 명의 한 회차 전체"""
    __tablename__ = "submissions"
    submission_id = Column(String(16), primary_key=True)
    student_id    = Column(String(64), ForeignKey("students.student_id"), nullable=False)
    problem_id    = Column(String(32), ForeignKey("essay_problems.problem_id"), nullable=True)
    # 제출 메타
    academy_name  = Column(String(128), default="")   # 학원명 (리포트 표지용)
    submit_date   = Column(String(32),  default="")   # 제출일
    status        = Column(String(32),  default="pending")
    error_message = Column(Text, default="")
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = relationship("StudentORM", back_populates="submissions")
    problem = relationship("EssayProblemORM", back_populates="submissions")
    items   = relationship("SubmissionItemORM", back_populates="submission",
                           cascade="all, delete-orphan",
                           order_by="SubmissionItemORM.item_number")

    __table_args__ = (
        Index("ix_sub_student", "student_id"),
        Index("ix_sub_problem", "problem_id"),
        Index("ix_sub_status",  "status"),
        Index("ix_sub_created", "created_at"),
    )

    def to_dict(self):
        return {
            "submission_id": self.submission_id,
            "student_id":    self.student_id,
            "student_name":  self.student.name if self.student else "",
            "problem_id":    self.problem_id,
            "problem_title": self.problem.title if self.problem else "",
            "academy_name":  self.academy_name,
            "submit_date":   self.submit_date,
            "status":        self.status,
            "items":         [i.to_dict() for i in self.items],
            "total_score":   sum(i.score or 0 for i in self.items if i.score),
            "item_count":    len(self.items),
            "created_at":    self.created_at.isoformat() if self.created_at else "",
            "updated_at":    self.updated_at.isoformat() if self.updated_at else "",
        }


class SubmissionItemORM(Base):
    """문항 단위 — 제출 1건 안의 문항 하나"""
    __tablename__ = "submission_items"
    item_id       = Column(String(32), primary_key=True)
    submission_id = Column(String(16), ForeignKey("submissions.submission_id"), nullable=False)
    item_number   = Column(Integer, nullable=False)     # 1,2,3...
    problem_id    = Column(String(32), ForeignKey("essay_problems.problem_id"), nullable=True)
    problem_type  = Column(String(64), default="")      # 요약-설명형 등
    # 이미지 (여러 장 가능)
    image_paths_json = Column(Text, default="[]")
    # OCR
    ocr_text      = Column(Text, default="")
    ocr_confidence = Column(Float, default=0.0)
    # LLM 첨삭 결과
    llm_result_json = Column(Text, default="{}")        # {numbered_text, strengths, weaknesses, improvements, summary, char_count}
    # 교사 편집본
    teacher_result_json = Column(Text, default="{}")    # LLM 결과를 교사가 수정한 최종본
    # 점수
    score         = Column(Float, nullable=True)
    max_score     = Column(Float, default=100.0)
    # 상태
    status        = Column(String(32), default="pending")  # pending/ocr_done/evaluated/teacher_done
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submission = relationship("SubmissionORM", back_populates="items")

    __table_args__ = (
        Index("ix_item_submission", "submission_id"),
    )

    @property
    def image_paths(self):
        return json.loads(self.image_paths_json or "[]")
    @image_paths.setter
    def image_paths(self, v):
        self.image_paths_json = json.dumps(v, ensure_ascii=False)

    @property
    def llm_result(self):
        return json.loads(self.llm_result_json or "{}")
    @llm_result.setter
    def llm_result(self, v):
        self.llm_result_json = json.dumps(v, ensure_ascii=False)

    @property
    def teacher_result(self):
        return json.loads(self.teacher_result_json or "{}")
    @teacher_result.setter
    def teacher_result(self, v):
        self.teacher_result_json = json.dumps(v, ensure_ascii=False)

    def to_dict(self):
        # 교사 편집본이 있으면 우선, 없으면 LLM 결과
        final = self.teacher_result if self.teacher_result else self.llm_result
        return {
            "item_id":       self.item_id,
            "submission_id": self.submission_id,
            "item_number":   self.item_number,
            "problem_id":    self.problem_id,
            "problem_type":  self.problem_type,
            "image_paths":   self.image_paths,
            "ocr_text":      self.ocr_text,
            "ocr_confidence": self.ocr_confidence,
            "llm_result":    self.llm_result,
            "teacher_result": self.teacher_result,
            "final_result":  final,
            "score":         self.score,
            "max_score":     self.max_score,
            "status":        self.status,
            "created_at":    self.created_at.isoformat() if self.created_at else "",
        }


def init_db():
    os.makedirs("./data", exist_ok=True)
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class ProblemGroupORM(Base):
    """
    문제 그룹 — 한 묶음으로 출제되는 문항들
    예: 1권 5강 (문항 1,2,3번), 고려대 2025 기출 (문항 1,2번)
    """
    __tablename__ = "problem_groups"

    group_id    = Column(String(32), primary_key=True)   # 예: reg_1_05, univ_korea_2025
    title       = Column(String(256), nullable=False)    # 예: 1권 5강, 고려대 2025학년도 기출
    category    = Column(String(8),  default="reg")      # reg / univ
    # 정규반용
    vol         = Column(Integer, nullable=True)         # 권 (1~4)
    lecture     = Column(Integer, nullable=True)         # 강 (1~8)
    # 대학별용
    university  = Column(String(64), default="")
    year        = Column(String(8),  default="")
    exam_type   = Column(String(16), default="")         # 기출 / 모의
    # 문항 순서 (JSON 배열)  예: ["reg_1_05_1","reg_1_05_2","reg_1_05_3"]
    problem_ids_json = Column(Text, default="[]")
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def problem_ids(self) -> list:
        return json.loads(self.problem_ids_json or "[]")

    @problem_ids.setter
    def problem_ids(self, v: list):
        self.problem_ids_json = json.dumps(v, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "group_id":    self.group_id,
            "title":       self.title,
            "category":    self.category,
            "vol":         self.vol,
            "lecture":     self.lecture,
            "university":  self.university,
            "year":        self.year,
            "exam_type":   self.exam_type,
            "problem_ids": self.problem_ids,
            "active":      self.active,
            "created_at":  self.created_at.isoformat() if self.created_at else "",
        }


class AppSettingORM(Base):
    """앱 설정 키-값 저장소"""
    __tablename__ = "app_settings"
    key        = Column(String(64), primary_key=True)
    value      = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

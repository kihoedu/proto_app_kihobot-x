#!/usr/bin/env python3
"""
시드 데이터 import 도구 (학원용)
=====================================
박기호논술이 GitHub 으로 배포한 시드 JSON 을
학원 환경의 DB 에 import 합니다.

학생 데이터·평가 이력은 절대 영향받지 않습니다 (시드에 포함 안 됨).

사용법:
  # 기본: 최신 시드 자동 import (data/seed/seed_latest.json)
  python import_seed.py

  # 특정 시드 파일 지정
  python import_seed.py data/seed/seed_v1_2026-05-03.json

  # 모드 선택
  python import_seed.py --mode upsert    # 같은 ID는 덮어쓰기 (기본)
  python import_seed.py --mode skip      # 같은 ID는 건너뛰기
  python import_seed.py --dry-run        # 실제 변경 없이 미리보기

  # 사일런트 (자동 import 용 — 서버 시작 훅에서 사용)
  python import_seed.py --silent
"""
import os
import sys
import json
import argparse
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from eval_engine.models import (
    SessionLocal, init_db,
    SystemPromptORM, EssayProblemORM, ProblemGroupORM,
)
from datetime import datetime


SUPPORTED_VERSIONS = ["1.0"]


def import_seed(seed_path: Path, mode: str = "upsert",
                dry_run: bool = False, silent: bool = False) -> dict:
    """시드 JSON 을 읽어 DB 에 적용. 통계 dict 반환."""
    if not seed_path.exists():
        raise FileNotFoundError(f"시드 파일 없음: {seed_path}")

    seed = json.loads(seed_path.read_text(encoding="utf-8"))

    # 버전 체크
    meta = seed.get("_meta", {})
    version = meta.get("version", "0")
    if version not in SUPPORTED_VERSIONS:
        if not silent:
            print(f"⚠️  지원 안 하는 시드 버전: {version} "
                  f"(지원: {SUPPORTED_VERSIONS})")
        # 강제 진행은 안 함 — 호환성 문제 방지

    init_db()
    db = SessionLocal()
    stats = {
        "system_prompts": {"created": 0, "updated": 0, "skipped": 0},
        "essay_problems": {"created": 0, "updated": 0, "skipped": 0},
        "problem_groups": {"created": 0, "updated": 0, "skipped": 0},
    }

    try:
        # ── 1. 시스템 프롬프트 ──
        for sp in seed.get("system_prompts", []):
            existing = db.query(SystemPromptORM).filter_by(
                prompt_id=sp["prompt_id"]
            ).first()

            if existing:
                if mode == "skip":
                    stats["system_prompts"]["skipped"] += 1
                    continue
                # upsert
                if not dry_run:
                    existing.name        = sp["name"]
                    existing.description = sp.get("description", "")
                    existing.content     = sp["content"]
                    existing.is_default  = bool(sp.get("is_default", False))
                    existing.active      = True
                    existing.updated_at  = datetime.utcnow()
                stats["system_prompts"]["updated"] += 1
            else:
                if not dry_run:
                    db.add(SystemPromptORM(
                        prompt_id   = sp["prompt_id"],
                        name        = sp["name"],
                        description = sp.get("description", ""),
                        content     = sp["content"],
                        is_default  = bool(sp.get("is_default", False)),
                        active      = True,
                    ))
                stats["system_prompts"]["created"] += 1

        # is_default 충돌 처리: 시드에 default 가 있으면 다른 것들 default 해제
        if not dry_run:
            seed_defaults = [sp["prompt_id"] for sp in seed.get("system_prompts", [])
                            if sp.get("is_default")]
            if seed_defaults:
                # 시드에서 default 로 지정된 것 외에는 모두 default 해제
                db.query(SystemPromptORM).filter(
                    ~SystemPromptORM.prompt_id.in_(seed_defaults)
                ).update({"is_default": False}, synchronize_session=False)

        # ── 2. 논술 문제 ──
        for p in seed.get("essay_problems", []):
            existing = db.query(EssayProblemORM).filter_by(
                problem_id=p["problem_id"]
            ).first()

            if existing:
                if mode == "skip":
                    stats["essay_problems"]["skipped"] += 1
                    continue
                if not dry_run:
                    existing.title            = p["title"]
                    existing.subject          = p.get("subject", "")
                    existing.year             = p.get("year", "")
                    existing.university       = p.get("university", "")
                    existing.time_limit       = p.get("time_limit", 0)
                    existing.question         = p["question"]
                    existing.passages         = p.get("passages", "")
                    existing.sample_answer    = p.get("sample_answer", "")
                    existing.scoring_criteria = p.get("scoring_criteria", "")
                    existing.prompt_template  = p.get("prompt_template", "")
                    existing.system_prompt_id = p.get("system_prompt_id")
                    if p.get("score_weights"):
                        existing.score_weights = p["score_weights"]
                    existing.active     = True
                    existing.updated_at = datetime.utcnow()
                stats["essay_problems"]["updated"] += 1
            else:
                if not dry_run:
                    new_p = EssayProblemORM(
                        problem_id       = p["problem_id"],
                        title            = p["title"],
                        subject          = p.get("subject", ""),
                        year             = p.get("year", ""),
                        university       = p.get("university", ""),
                        time_limit       = p.get("time_limit", 0),
                        question         = p["question"],
                        passages         = p.get("passages", ""),
                        sample_answer    = p.get("sample_answer", ""),
                        scoring_criteria = p.get("scoring_criteria", ""),
                        prompt_template  = p.get("prompt_template", ""),
                        system_prompt_id = p.get("system_prompt_id"),
                        active           = True,
                    )
                    if p.get("score_weights"):
                        new_p.score_weights = p["score_weights"]
                    db.add(new_p)
                stats["essay_problems"]["created"] += 1

        # ── 3. 문제 그룹 ──
        for g in seed.get("problem_groups", []):
            existing = db.query(ProblemGroupORM).filter_by(
                group_id=g["group_id"]
            ).first()

            if existing:
                if mode == "skip":
                    stats["problem_groups"]["skipped"] += 1
                    continue
                if not dry_run:
                    existing.title      = g["title"]
                    existing.category   = g.get("category", "reg")
                    existing.vol        = g.get("vol")
                    existing.lecture    = g.get("lecture")
                    existing.university = g.get("university", "")
                    existing.year       = g.get("year", "")
                    existing.exam_type  = g.get("exam_type", "")
                    existing.problem_ids = g.get("problem_ids", [])
                    existing.active     = True
                    existing.updated_at = datetime.utcnow()
                stats["problem_groups"]["updated"] += 1
            else:
                if not dry_run:
                    new_g = ProblemGroupORM(
                        group_id   = g["group_id"],
                        title      = g["title"],
                        category   = g.get("category", "reg"),
                        vol        = g.get("vol"),
                        lecture    = g.get("lecture"),
                        university = g.get("university", ""),
                        year       = g.get("year", ""),
                        exam_type  = g.get("exam_type", ""),
                        active     = True,
                    )
                    new_g.problem_ids = g.get("problem_ids", [])
                    db.add(new_g)
                stats["problem_groups"]["created"] += 1

        if not dry_run:
            db.commit()

    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()

    return {"meta": meta, "stats": stats}


def auto_import_if_empty(silent: bool = True):
    """서버 시작 훅에서 호출하는 자동 import.
    
    DB 가 비어있고 (problems 0개) seed_latest.json 이 있으면 자동 import.
    이미 데이터가 있으면 아무것도 안 함.
    """
    init_db()
    db = SessionLocal()
    try:
        problem_count = db.query(EssayProblemORM).filter_by(active=True).count()
        if problem_count > 0:
            if not silent:
                print(f"DB 에 이미 {problem_count}개 문제 있음 — 자동 import 스킵")
            return None
    finally:
        db.close()

    seed_latest = Path("data/seed/seed_latest.json")
    if not seed_latest.exists():
        if not silent:
            print(f"seed_latest.json 없음 — 자동 import 스킵")
        return None

    if not silent:
        print(f"📦 신규 환경 감지 — seed_latest.json 자동 import 시작")
    return import_seed(seed_latest, mode="upsert", silent=silent)


def main():
    parser = argparse.ArgumentParser(
        description="박기호논술 시드 데이터 import"
    )
    parser.add_argument(
        "seed_file", nargs="?", default="data/seed/seed_latest.json",
        help="시드 JSON 파일 경로 (기본: data/seed/seed_latest.json)"
    )
    parser.add_argument(
        "--mode", choices=["upsert", "skip"], default="upsert",
        help="upsert: 같은 ID는 덮어쓰기 (기본) / skip: 같은 ID는 건너뛰기"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="실제 변경 없이 미리보기"
    )
    parser.add_argument(
        "--silent", action="store_true",
        help="출력 최소화"
    )
    args = parser.parse_args()

    seed_path = Path(args.seed_file)

    if not args.silent:
        print("=" * 60)
        print(f"📦 시드 데이터 import")
        print(f"   파일: {seed_path}")
        print(f"   모드: {args.mode}{'  [DRY-RUN]' if args.dry_run else ''}")
        print("=" * 60)

    try:
        result = import_seed(
            seed_path,
            mode=args.mode,
            dry_run=args.dry_run,
            silent=args.silent
        )
    except FileNotFoundError as e:
        print(f"❌ {e}")
        print(f"   힌트: 시드 파일이 GitHub 에서 같이 받아졌는지 확인하세요.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Import 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if args.silent:
        return

    meta = result["meta"]
    stats = result["stats"]

    print()
    print(f"✅ Import {'미리보기' if args.dry_run else '완료'}!")
    print()
    print(f"   📌 시드 정보")
    print(f"      라벨:   {meta.get('label') or '(없음)'}")
    print(f"      생성:   {meta.get('exported_at', '-')[:19]}")
    print(f"      버전:   {meta.get('version', '-')}")
    print()
    print(f"   📊 결과")

    def _row(label, key):
        s = stats[key]
        return (f"      {label:<14} "
                f"신규 {s['created']:3d}  "
                f"갱신 {s['updated']:3d}  "
                f"건너뜀 {s['skipped']:3d}")

    print(_row("시스템 프롬프트", "system_prompts"))
    print(_row("논술 문제",       "essay_problems"))
    print(_row("문제 그룹",       "problem_groups"))
    print()

    if args.dry_run:
        print("💡 실제 적용하려면 --dry-run 빼고 다시 실행하세요.")
    print("=" * 60)


if __name__ == "__main__":
    main()

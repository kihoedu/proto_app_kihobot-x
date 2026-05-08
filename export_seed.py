#!/usr/bin/env python3
"""
시드 데이터 export 도구 (선생님용)
=====================================
박기호논술의 핵심 자산 (논술 문제 + 그룹 + 시스템 프롬프트) 을
JSON 파일로 내보내서 GitHub 으로 학원에 일방향 배포할 수 있게 합니다.

내보내는 데이터:
  ✅ system_prompts  : 시스템 프롬프트 (역할 설정 / 평가 원칙)
  ✅ essay_problems  : 논술 문제 (문제·제시문·예시답안·채점기준·매트릭스)
  ✅ problem_groups  : 문제 그룹 (1권 5강, 고려대 2025 등)

내보내지 않는 데이터 (학원 운영 데이터 — 개인정보):
  ❌ students        : 학생 정보
  ❌ submissions     : 제출 이력
  ❌ submission_items: 답안 / 첨삭 결과
  ❌ app_settings    : 앱 설정 (모델 토글 등 학원별 다름)

사용법:
  python export_seed.py
    → data/seed/seed_YYYYMMDD.json + seed_latest.json 생성

  python export_seed.py --label "1권 완성"
    → data/seed/seed_v1_2026-05-03.json + seed_latest.json 생성

  python export_seed.py --output data/seed/custom.json
    → 지정 경로로 저장
"""
import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 추가 (스크립트 단독 실행 지원)
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from eval_engine.models import (
    SessionLocal, init_db,
    SystemPromptORM, EssayProblemORM, ProblemGroupORM,
)


SEED_VERSION = "1.0"  # 시드 포맷 버전 — 향후 호환성 체크용


def export_seed(output_path: Path, label: str = "") -> dict:
    """현재 DB에서 시드 데이터를 추출해 JSON 파일로 저장."""
    init_db()
    db = SessionLocal()
    try:
        # ── 1. 시스템 프롬프트 ──
        prompts = []
        for p in db.query(SystemPromptORM).filter_by(active=True).all():
            prompts.append({
                "prompt_id":   p.prompt_id,
                "name":        p.name,
                "description": p.description or "",
                "content":     p.content,
                "is_default":  bool(p.is_default),
            })

        # ── 2. 논술 문제 ──
        problems = []
        for p in db.query(EssayProblemORM).filter_by(active=True).all():
            problems.append({
                "problem_id":       p.problem_id,
                "title":            p.title,
                "subject":          p.subject or "",
                "year":             p.year or "",
                "university":       p.university or "",
                "time_limit":       p.time_limit or 0,
                "question":         p.question,
                "passages":         p.passages or "",
                "sample_answer":    p.sample_answer or "",
                "scoring_criteria": p.scoring_criteria or "",
                "prompt_template":  p.prompt_template or "",
                "score_weights":    p.score_weights,
                "system_prompt_id": p.system_prompt_id,
            })

        # ── 3. 문제 그룹 ──
        groups = []
        for g in db.query(ProblemGroupORM).filter_by(active=True).all():
            groups.append({
                "group_id":    g.group_id,
                "title":       g.title,
                "category":    g.category or "reg",
                "vol":         g.vol,
                "lecture":     g.lecture,
                "university":  g.university or "",
                "year":        g.year or "",
                "exam_type":   g.exam_type or "",
                "problem_ids": g.problem_ids,
            })

        seed = {
            "_meta": {
                "version":     SEED_VERSION,
                "exported_at": datetime.now().isoformat(),
                "label":       label,
                "counts": {
                    "system_prompts":  len(prompts),
                    "essay_problems":  len(problems),
                    "problem_groups":  len(groups),
                },
            },
            "system_prompts": prompts,
            "essay_problems": problems,
            "problem_groups": groups,
        }

        # 저장
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(seed, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return seed
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="박기호논술 시드 데이터 export"
    )
    parser.add_argument(
        "--label", default="",
        help='시드 라벨 (예: "1권 완성"). 파일명·메타에 포함됨'
    )
    parser.add_argument(
        "--output", default=None,
        help="저장 경로 (기본: data/seed/seed_YYYYMMDD.json)"
    )
    parser.add_argument(
        "--no-latest", action="store_true",
        help="seed_latest.json 도 같이 생성 (기본: 생성)"
    )
    args = parser.parse_args()

    # 출력 경로 결정
    if args.output:
        output_path = Path(args.output)
    else:
        date_str = datetime.now().strftime("%Y%m%d")
        if args.label:
            # 라벨에서 파일명에 안전한 문자만 남김
            safe_label = "".join(c if c.isalnum() or c in "-_가-힣" else "_"
                                 for c in args.label).strip("_")
            filename = f"seed_{date_str}_{safe_label}.json"
        else:
            filename = f"seed_{date_str}.json"
        output_path = Path("data/seed") / filename

    # export 실행
    print("=" * 60)
    print(f"📦 시드 데이터 export 중...")
    print(f"   경로: {output_path}")
    if args.label:
        print(f"   라벨: {args.label}")
    print("=" * 60)

    seed = export_seed(output_path, args.label)
    counts = seed["_meta"]["counts"]
    file_size = output_path.stat().st_size / 1024

    print()
    print(f"✅ Export 완료!")
    print(f"   📝 시스템 프롬프트: {counts['system_prompts']}개")
    print(f"   📚 논술 문제:       {counts['essay_problems']}개")
    print(f"   📁 문제 그룹:       {counts['problem_groups']}개")
    print(f"   💾 파일 크기:       {file_size:.1f} KB")
    print(f"   📄 저장 위치:       {output_path.absolute()}")

    # seed_latest.json 도 생성 (자동 import 용)
    if not args.no_latest:
        latest_path = output_path.parent / "seed_latest.json"
        latest_path.write_text(
            output_path.read_text(encoding="utf-8"),
            encoding="utf-8"
        )
        print(f"   📌 latest 사본:     {latest_path.absolute()}")

    print()
    print("=" * 60)
    print("💡 다음 단계:")
    print(f"   1. git add {output_path.parent}")
    print(f"   2. git commit -m \"data: 시드 업데이트\"")
    print(f"   3. git push origin main")
    print("=" * 60)


if __name__ == "__main__":
    main()

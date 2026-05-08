#!/usr/bin/env python3
"""
첨삭 모델 A/B 비교 도구
=========================
같은 학생 답안 + 문제를 여러 LLM 모델로 동시 첨삭하여 결과를 나란히 비교.

사용법:
  # 1) 인자로 답안 텍스트 + 문제 ID 직접 전달
  python compare_models.py --answer "학생답안텍스트..." --problem-id reg_1_01_1

  # 2) 텍스트 파일 + 문제 ID
  python compare_models.py --answer-file answer.txt --problem-id reg_1_01_1

  # 3) 이미 평가된 submission item 의 OCR 텍스트로 비교
  python compare_models.py --item-id <item_uuid>

  # 4) 모델 선택 (기본: gemini-flash, gemini-pro, sonnet, opus 모두)
  python compare_models.py --answer-file answer.txt --problem-id <pid> \\
      --models gemini-flash sonnet

출력:
  data/model_comparison/comparison_<timestamp>.html
  (브라우저에서 열어서 나란히 비교)
"""
import os
import sys
import time
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path 에 추가 (스크립트 단독 실행 지원)
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("kihobot.compare")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ────────────────────────────────────────────────────────────
# 비교할 모델 프리셋
# ────────────────────────────────────────────────────────────
MODEL_PRESETS = {
    "gemini-flash": {
        "label": "Gemini 2.5 Flash (현재)",
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "price_in": 0.15,    # USD per 1M tokens
        "price_out": 0.60,
    },
    "gemini-pro": {
        "label": "Gemini 1.5 Pro",
        "provider": "gemini",
        "model": "gemini-1.5-pro",
        "price_in": 1.25,
        "price_out": 5.00,
    },
    "sonnet": {
        "label": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "price_in": 3.00,
        "price_out": 15.00,
    },
    "opus": {
        "label": "Claude Opus 4.7",
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "price_in": 15.00,
        "price_out": 75.00,
    },
}


def call_model(preset_key: str, ocr_text: str, problem: dict | None,
               system_prompt: str, item_number: int = 1) -> dict:
    """단일 모델로 첨삭 호출. 환경변수 + DB 설정을 임시 우회·복구."""
    preset = MODEL_PRESETS[preset_key]

    # 환경변수 임시 변경
    saved = {
        "LLM_PROVIDER": os.environ.get("LLM_PROVIDER"),
        "GEMINI_MODEL": os.environ.get("GEMINI_MODEL"),
        "ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL"),
    }

    # DB 설정도 확인 — DB에 값이 있으면 환경변수보다 우선되므로 우회 필요
    from eval_engine.services.crud import (
        get_setting, set_setting, get_db,
    )
    from eval_engine.models import AppSettingORM
    saved_db = {
        "llm_provider": get_setting("llm_provider", ""),
        "gemini_model": get_setting("gemini_model", ""),
    }

    def _clear_db_keys(keys):
        """DB 설정 임시 제거 (환경변수가 우선되도록)"""
        with get_db() as db:
            for k in keys:
                row = db.query(AppSettingORM).filter_by(key=k).first()
                if row:
                    db.delete(row)

    def _restore_db_keys(saved_dict):
        """우회했던 DB 설정 복구"""
        for k, v in saved_dict.items():
            if v:
                set_setting(k, v)

    try:
        # 1) DB 설정 임시 제거 (환경변수 우선 적용)
        _clear_db_keys(["llm_provider", "gemini_model"])

        # 2) 환경변수 설정
        os.environ["LLM_PROVIDER"] = preset["provider"]
        if preset["provider"] == "gemini":
            os.environ["GEMINI_MODEL"] = preset["model"]
        elif preset["provider"] == "anthropic":
            os.environ["ANTHROPIC_MODEL"] = preset["model"]

        # annotate_item 은 매번 _get_llm() 호출하므로 환경변수 변경 즉시 반영
        from eval_engine.agents.annotation_agent import annotate_item

        t0 = time.time()
        result = annotate_item(
            ocr_text=ocr_text,
            problem=problem,
            system_prompt_content=system_prompt,
            item_number=item_number,
        )
        elapsed = time.time() - t0

        # 메타데이터 추가
        result["_meta"] = {
            "preset_key": preset_key,
            "label": preset["label"],
            "provider": preset["provider"],
            "model": preset["model"],
            "elapsed_sec": round(elapsed, 1),
            "input_chars": len(ocr_text),
            "output_chars": len(result.get("raw", "")),
            # 비용 추정 (대략 1자 = 1.4 토큰 가정)
            "estimated_cost_usd": round(
                (len(ocr_text) * 1.4 / 1_000_000) * preset["price_in"]
                + (len(result.get("raw", "")) * 1.4 / 1_000_000) * preset["price_out"],
                5
            ),
            "ok": True,
        }
        return result

    except Exception as e:
        logger.error(f"[{preset_key}] 호출 실패: {e}")
        return {
            "_meta": {
                "preset_key": preset_key,
                "label": preset["label"],
                "provider": preset["provider"],
                "model": preset["model"],
                "elapsed_sec": 0,
                "ok": False,
                "error": str(e),
            },
            "raw": "",
            "numbered_text": "",
            "strengths": "",
            "weaknesses": "",
            "improvements": "",
            "summary": "",
            "score": None,
            "citation_check": {"total": 0, "verified": 0, "missing": []},
        }
    finally:
        # 환경변수 복구
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # DB 설정 복구
        _restore_db_keys(saved_db)


def html_escape(s: str) -> str:
    """HTML 출력용 이스케이프."""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;")
                  .replace("<", "&lt;")
                  .replace(">", "&gt;")
                  .replace("\n", "<br>"))


def render_html(comparison: dict) -> str:
    """비교 결과를 HTML 리포트로 변환."""
    answer = comparison["answer"]
    problem_summary = comparison["problem_summary"]
    results = comparison["results"]

    # 컬럼 너비 (모델 수에 따라)
    col_count = len(results)
    col_width_pct = max(20, 100 // col_count)

    # 모델별 컬럼 헤더
    headers = ""
    for r in results:
        m = r["_meta"]
        ok = m.get("ok", False)
        cost_str = f"${m.get('estimated_cost_usd', 0):.4f}" if ok else "-"
        elapsed = f"{m.get('elapsed_sec', 0):.1f}s" if ok else "-"
        headers += f"""
        <th style="width:{col_width_pct}%; vertical-align:top;">
          <div class="model-name">{html_escape(m['label'])}</div>
          <div class="model-meta">{html_escape(m.get('model', ''))}</div>
          <div class="model-stats">⏱ {elapsed} · 💰 {cost_str}</div>
        </th>"""

    # 각 행: 첨삭 항목별로 모델 결과 비교
    rows = []

    def make_row(label: str, key: str, formatter=None):
        """모델별로 같은 키 값을 한 행에 나열."""
        cells = ""
        for r in results:
            v = r.get(key, "")
            if formatter:
                v = formatter(v, r)
            cells += f'<td class="cell">{v}</td>'
        return f'<tr><td class="label">{label}</td>{cells}</tr>'

    # 인용 검증 결과 포맷
    def fmt_citation(cc: dict, r: dict) -> str:
        if not cc:
            return "-"
        total = cc.get("total", 0)
        verified = cc.get("verified", 0)
        missing = cc.get("missing", [])
        if total == 0:
            return '<span class="muted">N/A</span>'
        ratio = verified / total
        cls = "ok" if ratio >= 0.9 else ("warn" if ratio >= 0.7 else "bad")
        html = f'<div class="citation-summary {cls}">{verified}/{total} 검증 통과</div>'
        if missing:
            html += '<details><summary class="muted">⚠ 누락 인용 보기</summary><ul>'
            for m in missing:
                html += f'<li class="muted">[{m["idx"]}] {html_escape(m["quote"])}</li>'
            html += '</ul></details>'
        return html

    rows.append(make_row("점수", "score",
                         lambda v, r: f'<div class="score">{v if v is not None else "-"}</div>'))
    rows.append(make_row("인용 검증", "citation_check",
                         lambda v, r: fmt_citation(v, r)))
    rows.append(make_row("원문 (번호 부여)", "numbered_text",
                         lambda v, r: f'<div class="prose">{html_escape(v)}</div>'))
    rows.append(make_row("장점", "strengths",
                         lambda v, r: f'<div class="prose">{html_escape(v)}</div>'))
    rows.append(make_row("단점", "weaknesses",
                         lambda v, r: f'<div class="prose">{html_escape(v)}</div>'))
    rows.append(make_row("보완할 부분", "improvements",
                         lambda v, r: f'<div class="prose">{html_escape(v)}</div>'))
    rows.append(make_row("총평", "summary",
                         lambda v, r: f'<div class="prose">{html_escape(v)}</div>'))

    rows_html = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>첨삭 모델 비교 — kihobot_x</title>
<style>
  body {{ font-family: 'Malgun Gothic', sans-serif; margin: 24px; background: #f4f4f4; }}
  h1 {{ font-size: 22px; margin-bottom: 8px; }}
  .header-info {{ background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 20px;
                  box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  .header-info h3 {{ margin: 0 0 8px; font-size: 14px; color: #555; }}
  .header-info .text {{ font-size: 13px; color: #333; line-height: 1.6;
                        max-height: 120px; overflow-y: auto; padding: 8px;
                        background: #fafafa; border-left: 3px solid #ccc; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 8px; overflow: hidden;
           box-shadow: 0 1px 3px rgba(0,0,0,0.05); table-layout: fixed; }}
  th {{ background: #2b2b2b; color: #fff; padding: 12px 8px; text-align: center;
        border-right: 1px solid #444; }}
  th:last-child {{ border-right: none; }}
  .model-name {{ font-size: 14px; font-weight: bold; }}
  .model-meta {{ font-size: 11px; color: #aaa; margin-top: 2px; }}
  .model-stats {{ font-size: 11px; color: #ffd600; margin-top: 4px; }}
  td {{ padding: 12px 10px; vertical-align: top; border-top: 1px solid #eee;
        border-right: 1px solid #eee; word-break: break-word; }}
  td:last-child {{ border-right: none; }}
  .label {{ width: 100px; background: #f8f8f8; font-weight: bold; color: #555;
            font-size: 12px; vertical-align: top; }}
  .cell {{ font-size: 13px; line-height: 1.6; color: #222; }}
  .prose {{ white-space: normal; }}
  .score {{ font-size: 28px; font-weight: bold; color: #2b6cb0; text-align: center; }}
  .citation-summary {{ display: inline-block; padding: 4px 10px;
                       border-radius: 4px; font-size: 12px; font-weight: bold; }}
  .citation-summary.ok {{ background: #d4edda; color: #155724; }}
  .citation-summary.warn {{ background: #fff3cd; color: #856404; }}
  .citation-summary.bad {{ background: #f8d7da; color: #721c24; }}
  .muted {{ color: #888; font-size: 11px; }}
  details summary {{ cursor: pointer; margin-top: 6px; }}
  details ul {{ font-size: 11px; padding-left: 18px; margin: 6px 0; }}
  .timestamp {{ color: #888; font-size: 12px; margin-bottom: 16px; }}
</style>
</head>
<body>
  <h1>📝 첨삭 모델 비교</h1>
  <div class="timestamp">생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>

  <div class="header-info">
    <h3>📋 문제 정보</h3>
    <div class="text">{html_escape(problem_summary)}</div>
  </div>

  <div class="header-info">
    <h3>✏️ 학생 답안 (입력)</h3>
    <div class="text">{html_escape(answer)}</div>
  </div>

  <table>
    <thead><tr><th class="label">항목</th>{headers}</tr></thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <div class="timestamp" style="margin-top:20px;">
    💡 평가 기준: ① 인용 정확성 (수정 전 문장이 학생 답안에 실재하는가)
    ② 톤 (사람 강사처럼 자연스러운가) ③ 첨삭 포인트의 적절성
    ④ 형식 준수 (4줄 구조 지키는가)
  </div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="첨삭 모델 A/B 비교 도구")
    parser.add_argument("--answer", help="학생 답안 텍스트 (직접)")
    parser.add_argument("--answer-file", help="학생 답안 텍스트 파일 경로")
    parser.add_argument("--problem-id", help="문제 ID (DB 에서 로드)")
    parser.add_argument("--item-id", help="평가 item ID (이미 OCR 된 답안 사용)")
    parser.add_argument("--item-number", type=int, default=1, help="문항 번호 (기본 1)")
    parser.add_argument("--models", nargs="+",
                        default=list(MODEL_PRESETS.keys()),
                        choices=list(MODEL_PRESETS.keys()),
                        help="비교할 모델 (기본: 전체)")
    parser.add_argument("--output-dir", default="data/model_comparison",
                        help="결과 HTML 저장 디렉토리")

    args = parser.parse_args()

    # ── 답안 텍스트 결정 ──
    ocr_text = None
    problem_id = args.problem_id

    if args.item_id:
        # DB 에서 OCR 텍스트 로드
        from eval_engine.models import SessionLocal, SubmissionItemORM
        db = SessionLocal()
        try:
            item = db.query(SubmissionItemORM).filter_by(item_id=args.item_id).first()
            if not item:
                logger.error(f"❌ item_id 를 찾을 수 없음: {args.item_id}")
                sys.exit(1)
            ocr_text = item.ocr_text
            problem_id = problem_id or item.problem_id
        finally:
            db.close()
    elif args.answer_file:
        ocr_text = Path(args.answer_file).read_text(encoding="utf-8")
    elif args.answer:
        ocr_text = args.answer
    else:
        logger.error("❌ --answer / --answer-file / --item-id 중 하나는 필수")
        sys.exit(1)

    if not ocr_text or not ocr_text.strip():
        logger.error("❌ 답안 텍스트가 비어있음")
        sys.exit(1)

    # ── 문제 정보 로드 ──
    from eval_engine.services.crud import get_problem, resolve_system_prompt_for_problem
    problem = get_problem(problem_id) if problem_id else None
    system_prompt = resolve_system_prompt_for_problem(problem)

    problem_summary = "(문제 정보 없음)"
    if problem:
        q = problem.get("question", "")[:200]
        problem_summary = f"[ID: {problem_id}] {q}{'...' if len(problem.get('question','')) > 200 else ''}"

    # ── 모델별 호출 ──
    logger.info("=" * 60)
    logger.info(f"📝 비교할 모델: {', '.join(args.models)}")
    logger.info(f"📋 문제: {problem_summary}")
    logger.info(f"✏️  답안 길이: {len(ocr_text)}자")
    logger.info("=" * 60)

    results = []
    for preset_key in args.models:
        logger.info(f"\n🤖 [{preset_key}] {MODEL_PRESETS[preset_key]['label']} 호출 중...")
        result = call_model(preset_key, ocr_text, problem, system_prompt, args.item_number)
        m = result["_meta"]
        if m.get("ok"):
            cc = result.get("citation_check") or {}
            logger.info(
                f"   ✅ 완료 ({m['elapsed_sec']}s, ${m['estimated_cost_usd']:.4f}) "
                f"점수 {result.get('score', '-')} · 인용 {cc.get('verified',0)}/{cc.get('total',0)}"
            )
        else:
            logger.info(f"   ❌ 실패: {m.get('error', 'unknown')}")
        results.append(result)

    # ── HTML 리포트 생성 ──
    comparison = {
        "answer": ocr_text,
        "problem_summary": problem_summary,
        "results": results,
        "timestamp": datetime.now().isoformat(),
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"comparison_{timestamp}.html"

    out_path.write_text(render_html(comparison), encoding="utf-8")

    # 비용 합계
    total_cost = sum(r["_meta"].get("estimated_cost_usd", 0) for r in results)
    total_time = sum(r["_meta"].get("elapsed_sec", 0) for r in results)

    logger.info("\n" + "=" * 60)
    logger.info(f"📊 총 비용: ${total_cost:.4f} (≈ ₩{int(total_cost * 1400)})")
    logger.info(f"⏱  총 소요: {total_time:.1f}초")
    logger.info(f"📄 결과: {out_path.absolute()}")
    logger.info("=" * 60)
    logger.info("\n💡 브라우저에서 위 파일을 열어 모델별 결과를 비교하세요.")


if __name__ == "__main__":
    main()

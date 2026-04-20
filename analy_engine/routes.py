#!/usr/bin/env python3
"""
EOLE 교안 자동화 웹 서비스 v3
PDF → JSON → DOCX + PPT 전체 자동 파이프라인
"""
import os
import sys
import json
import subprocess
import shutil
import uuid
import traceback
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger("kihobot.analy")

# ─── 경로 설정 ───
BASE = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE / "data" / "uploads"
OUTPUT_DIR = BASE / "data" / "outputs"
DATA_DIR = BASE / "data" / "lesson_json"

for d in [UPLOAD_DIR, OUTPUT_DIR, DATA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── APIRouter (main.py 에서 /analy prefix 로 include) ───
router = APIRouter()
templates = Jinja2Templates(directory=str(BASE / "analy_engine" / "templates"))


# ─── 유틸 ───
def load_data_items():
    """data/ 폴더의 JSON 파일 목록"""
    items = []
    for filepath in sorted(DATA_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            raw = filepath.read_text(encoding="utf-8")
            d = json.loads(raw)
            meta = d.get("meta", {})
            items.append({
                "filename": filepath.name,
                "university": meta.get("university", ""),
                "year": meta.get("year", ""),
                "track": meta.get("track", ""),
                "subtitle": meta.get("subtitle", ""),
                "questions": len(d.get("problemSets", [])),
            })
        except Exception as e:
            logger.warning(f"JSON 파싱 실패: {filepath.name} - {e}")
    return items


def list_output_files():
    """outputs/ 폴더의 파일 목록"""
    allowed = {".docx", ".pptx", ".md", ".json"}
    files = []
    for filepath in sorted(OUTPUT_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if filepath.suffix in allowed and filepath.is_file():
            files.append({
                "name": filepath.name,
                "size": filepath.stat().st_size,
                "ext": filepath.suffix,
            })
    return files


def safe_name_from_meta(meta: dict) -> str:
    """meta에서 안전한 파일명 생성"""
    uni = meta.get("university", "대학")
    year = meta.get("year", 0)
    track = meta.get("track", "").replace(" ", "").replace("/", "_")
    return f"{uni}_{year}_{track}"


# ─── 메인 페이지 ───
@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "items": load_data_items(),
            "output_files": list_output_files(),
        },
    )


# ─── 핵심 API: PDF → 전체 자동 생성 ───
@router.post("/api/auto-generate")
async def auto_generate(file: UploadFile = File(...)):
    """PDF 업로드 → JSON 추출 → 교안 DOCX + PPT 한 번에"""

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 업로드 가능합니다.")

    # PDF 저장
    uid = uuid.uuid4().hex[:8]
    pdf_filename = f"{uid}_{file.filename}"
    pdf_path = UPLOAD_DIR / pdf_filename

    try:
        with open(pdf_path, "wb") as out_file:
            shutil.copyfileobj(file.file, out_file)
        logger.info(f"📄 PDF 저장: {pdf_path} ({pdf_path.stat().st_size:,} bytes)")
    except Exception as e:
        logger.error(f"PDF 저장 실패: {e}")
        raise HTTPException(500, f"PDF 저장 실패: {str(e)}")

    results = {"pdf": file.filename, "steps": []}

    # ── Step 1: PDF → JSON ──
    data = None
    safe = None
    json_path = None

    try:
        logger.info("🤖 Step 1: PDF → JSON 변환 시작...")
        from analy_engine.services.pdf_to_json import convert_pdf_to_json
        data = convert_pdf_to_json(str(pdf_path))

        meta = data["meta"]
        safe = safe_name_from_meta(meta)
        json_path = DATA_DIR / f"{safe}.json"

        with open(json_path, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=2)

        results["json_file"] = json_path.name
        num_sets = len(data.get("problemSets", []))
        results["steps"].append(f"✅ JSON 추출 완료 ({num_sets}개 문제)")
        logger.info(f"✅ JSON 저장: {json_path.name} ({num_sets}개 문제)")

    except Exception as e:
        err_msg = f"JSON 추출 실패: {str(e)}"
        logger.error(f"❌ {err_msg}")
        logger.error(traceback.format_exc())
        results["steps"].append(f"❌ {err_msg}")
        return JSONResponse({"status": "error", **results}, status_code=500)

    # ── Step 2: JSON → 교안 DOCX ──
    try:
        logger.info("📑 Step 2: 교안 DOCX 생성 시작...")
        docx_name = f"{safe}_교안.docx"
        tmp_docx = OUTPUT_DIR / f"tmp_{docx_name}"
        final_docx = OUTPUT_DIR / docx_name

        node_cmd = [
            "node",
            str(BASE / "analy_engine" / "generate_gyoan.js"),
            str(tmp_docx),
            str(json_path),
        ]
        logger.info(f"  실행: {' '.join(node_cmd)}")

        proc = subprocess.run(
            node_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(BASE),
            timeout=60,
        )

        if proc.returncode != 0:
            logger.error(f"  Node.js stderr: {proc.stderr}")
            raise RuntimeError(f"Node.js 실행 실패: {proc.stderr[:500]}")

        logger.info(f"  Node.js stdout: {(proc.stdout or '').strip()}")

        # 후처리 (wordWrap 패치)
        from analy_engine.services.postprocess import patch_docx
        patch_docx(str(tmp_docx), str(final_docx))

        if tmp_docx.exists():
            tmp_docx.unlink()

        results["docx_file"] = docx_name
        results["docx_size"] = final_docx.stat().st_size
        results["steps"].append(f"✅ 교안 DOCX ({final_docx.stat().st_size:,} bytes)")
        logger.info(f"✅ DOCX 완료: {docx_name}")

    except Exception as e:
        err_msg = f"DOCX 생성 실패: {str(e)}"
        logger.error(f"❌ {err_msg}")
        logger.error(traceback.format_exc())
        results["steps"].append(f"❌ {err_msg}")

    # ── Step 3: JSON → PPT ──
    try:
        logger.info("📊 Step 3: PPT 생성 시작...")
        from analy_engine.services.generate_pptx import generate_pptx

        pptx_name = f"{safe}.pptx"
        pptx_path = OUTPUT_DIR / pptx_name
        generate_pptx(data, str(pptx_path))

        results["pptx_file"] = pptx_name
        results["pptx_size"] = pptx_path.stat().st_size
        results["steps"].append(f"✅ PPT ({pptx_path.stat().st_size:,} bytes)")
        logger.info(f"✅ PPT 완료: {pptx_name}")

    except Exception as e:
        err_msg = f"PPT 생성 실패: {str(e)}"
        logger.error(f"❌ {err_msg}")
        logger.error(traceback.format_exc())
        results["steps"].append(f"❌ {err_msg}")

    results["status"] = "ok"
    logger.info(f"🎉 전체 완료: {results['steps']}")
    return JSONResponse(results)


# ─── 개별: DOCX만 생성 ───
@router.post("/api/generate-docx")
async def api_generate_docx(json_file: str = Form(...)):
    json_path = DATA_DIR / json_file
    if not json_path.exists():
        raise HTTPException(404, f"데이터 파일 없음: {json_file}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        meta = data["meta"]
        safe = safe_name_from_meta(meta)
        docx_name = f"{safe}_교안.docx"
        tmp = OUTPUT_DIR / f"tmp_{docx_name}"
        final = OUTPUT_DIR / docx_name

        proc = subprocess.run(
            ["node", str(BASE / "analy_engine" / "generate_gyoan.js"), str(tmp), str(json_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(BASE), timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[:500])

        from analy_engine.services.postprocess import patch_docx
        patch_docx(str(tmp), str(final))
        if tmp.exists():
            tmp.unlink()

        return JSONResponse({"status": "ok", "docx_file": docx_name, "size": final.stat().st_size})
    except Exception as e:
        logger.error(traceback.format_exc())
        raise HTTPException(500, str(e))


# ─── 개별: PPT만 생성 ───
@router.post("/api/generate-pptx")
async def api_generate_pptx(json_file: str = Form(...)):
    json_path = DATA_DIR / json_file
    if not json_path.exists():
        raise HTTPException(404, f"데이터 파일 없음: {json_file}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        meta = data["meta"]
        safe = safe_name_from_meta(meta)
        pptx_name = f"{safe}.pptx"
        pptx_path = OUTPUT_DIR / pptx_name

        from analy_engine.services.generate_pptx import generate_pptx
        generate_pptx(data, str(pptx_path))

        return JSONResponse({"status": "ok", "pptx_file": pptx_name, "size": pptx_path.stat().st_size})
    except Exception as e:
        logger.error(traceback.format_exc())
        raise HTTPException(500, str(e))


# ─── MD 트랙: PDF → MD → JSON → 기존 렌더러 재활용 ───
@router.post("/api/md-generate")
async def md_generate(file: UploadFile = File(...)):
    """
    PDF 업로드 → MD 추출(DB용) → JSON 변환 → 기존 교안 DOCX + PPT
    
    기존 /api/auto-generate 와 달리:
    - 중간 단계에서 MD 를 생성하여 DB 자산으로 저장
    - MD 는 data/lesson_md/ 에 영구 보관
    - 최종 DOCX/PPT 는 기존 generate_gyoan.js · generate_pptx.py 재활용
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 업로드 가능합니다.")

    # MD 저장 디렉토리
    MD_DIR = BASE / "data" / "lesson_md"
    MD_DIR.mkdir(parents=True, exist_ok=True)

    # PDF 저장
    uid = uuid.uuid4().hex[:8]
    pdf_filename = f"{uid}_{file.filename}"
    pdf_path = UPLOAD_DIR / pdf_filename

    try:
        with open(pdf_path, "wb") as out_file:
            shutil.copyfileobj(file.file, out_file)
        logger.info(f"📄 PDF 저장: {pdf_path}")
    except Exception as e:
        logger.error(f"PDF 저장 실패: {e}")
        raise HTTPException(500, f"PDF 저장 실패: {str(e)}")

    results = {"pdf": file.filename, "steps": [], "track": "md"}

    # ── Step 1: PDF → MD ──
    md_result = None
    safe = None

    try:
        logger.info("🤖 Step 1: PDF → MD 변환 시작...")
        from analy_engine.services.pdf_to_md import convert_pdf_to_md
        md_result = convert_pdf_to_md(str(pdf_path))

        meta = md_result["meta"]
        safe = safe_name_from_meta(meta)

        md_path = MD_DIR / f"{safe}.md"
        md_path.write_text(md_result["full_md"], encoding="utf-8")

        results["md_file"] = md_path.name
        results["md_size"] = len(md_result["full_md"])
        problem_count = len(md_result["problem_mds"])
        results["steps"].append(f"✅ MD 추출 완료 ({problem_count}개 문제, {results['md_size']:,}자)")
        logger.info(f"✅ MD 저장: {md_path.name}")

    except Exception as e:
        err_msg = f"MD 추출 실패: {str(e)}"
        logger.error(f"❌ {err_msg}")
        logger.error(traceback.format_exc())
        results["steps"].append(f"❌ {err_msg}")
        return JSONResponse({"status": "error", **results}, status_code=500)

    # ── Step 2: MD → JSON (generate_gyoan.js 용) ──
    data = None
    json_path = None
    try:
        logger.info("🔄 Step 2: MD → JSON 변환...")
        from analy_engine.services.md_to_json import md_to_json
        data = md_to_json(md_result["full_md"])

        json_path = DATA_DIR / f"{safe}.json"
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        results["json_file"] = json_path.name
        results["steps"].append(f"✅ JSON 변환 완료 (렌더러 입력용)")
        logger.info(f"✅ JSON 저장: {json_path.name}")

    except Exception as e:
        err_msg = f"JSON 변환 실패: {str(e)}"
        logger.error(f"❌ {err_msg}")
        logger.error(traceback.format_exc())
        results["steps"].append(f"❌ {err_msg}")
        return JSONResponse({"status": "error", **results}, status_code=500)

    # ── Step 3: JSON → 교안 DOCX (기존 재활용) ──
    try:
        logger.info("📑 Step 3: 교안 DOCX 생성...")
        docx_name = f"{safe}_교안_MD.docx"
        tmp_docx = OUTPUT_DIR / f"tmp_{docx_name}"
        final_docx = OUTPUT_DIR / docx_name

        proc = subprocess.run(
            [
                "node",
                str(BASE / "analy_engine" / "generate_gyoan.js"),
                str(tmp_docx),
                str(json_path),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(BASE), timeout=60,
        )

        if proc.returncode != 0:
            raise RuntimeError(f"Node.js 실행 실패: {proc.stderr[:500]}")

        from analy_engine.services.postprocess import patch_docx
        patch_docx(str(tmp_docx), str(final_docx))

        if tmp_docx.exists():
            tmp_docx.unlink()

        results["docx_file"] = docx_name
        results["docx_size"] = final_docx.stat().st_size
        results["steps"].append(f"✅ 교안 DOCX ({final_docx.stat().st_size:,} bytes)")
        logger.info(f"✅ DOCX 완료: {docx_name}")

    except Exception as e:
        err_msg = f"DOCX 생성 실패: {str(e)}"
        logger.error(f"❌ {err_msg}")
        logger.error(traceback.format_exc())
        results["steps"].append(f"❌ {err_msg}")

    # ── Step 4: JSON → PPT (기존 재활용) ──
    try:
        logger.info("📊 Step 4: PPT 생성...")
        from analy_engine.services.generate_pptx import generate_pptx

        pptx_name = f"{safe}_MD.pptx"
        pptx_path = OUTPUT_DIR / pptx_name
        generate_pptx(data, str(pptx_path))

        results["pptx_file"] = pptx_name
        results["pptx_size"] = pptx_path.stat().st_size
        results["steps"].append(f"✅ PPT ({pptx_path.stat().st_size:,} bytes)")
        logger.info(f"✅ PPT 완료: {pptx_name}")

    except Exception as e:
        err_msg = f"PPT 생성 실패: {str(e)}"
        logger.error(f"❌ {err_msg}")
        logger.error(traceback.format_exc())
        results["steps"].append(f"❌ {err_msg}")

    results["status"] = "ok"
    logger.info(f"🎉 MD 트랙 완료: {results['steps']}")
    return JSONResponse(results)


# ─── MD 파일 직접 다운로드/조회 ───
@router.get("/api/md/{filename}")
async def get_md_content(filename: str):
    """MD 파일 원본 내용 반환 (뷰어·편집용)"""
    MD_DIR = BASE / "data" / "lesson_md"
    md_path = MD_DIR / filename
    if not md_path.exists():
        raise HTTPException(404, f"MD 파일 없음: {filename}")
    return JSONResponse({
        "filename": filename,
        "content": md_path.read_text(encoding="utf-8"),
        "size": md_path.stat().st_size,
    })


# ─── 다운로드 ───
@router.get("/download/{filename}")
async def download(filename: str):
    MD_DIR = BASE / "data" / "lesson_md"
    for folder in [OUTPUT_DIR, DATA_DIR, MD_DIR]:
        fpath = folder / filename
        if fpath.exists() and fpath.is_file():
            return FileResponse(str(fpath), filename=filename)
    raise HTTPException(404, f"파일 없음: {filename}")


# ─── 파일 삭제 ───
@router.delete("/api/delete/{filename}")
async def delete_file(filename: str):
    """개별 파일 삭제"""
    for folder in [OUTPUT_DIR, DATA_DIR]:
        fpath = folder / filename
        if fpath.exists() and fpath.is_file():
            fpath.unlink()
            logger.info(f"🗑️ 삭제: {fpath}")
            return JSONResponse({"status": "ok", "deleted": filename})
    raise HTTPException(404, f"파일 없음: {filename}")


@router.post("/api/clear-all")
async def clear_all():
    """outputs/, data/, uploads/ 전체 비우기"""
    count = 0
    for folder in [OUTPUT_DIR, DATA_DIR, UPLOAD_DIR]:
        for fpath in folder.iterdir():
            if fpath.is_file() and fpath.name != ".gitkeep":
                fpath.unlink()
                count += 1
    logger.info(f"🗑️ 전체 삭제: {count}개 파일")
    return JSONResponse({"status": "ok", "deleted_count": count})


# ─── 상태 확인 ───
@router.get("/api/health")
async def health():
    """서버 상태 + 환경 확인"""
    checks = {}

    # Gemini API Key
    checks["gemini_key"] = "✅" if os.getenv("GEMINI_API_KEY") else "❌ .env에 GEMINI_API_KEY 설정 필요"

    # Poppler (pdftotext)
    poppler = os.getenv("POPPLER_PATH", "")
    if poppler:
        pdftotext = os.path.join(poppler, "pdftotext.exe") if os.name == "nt" else "pdftotext"
        checks["pdftotext"] = "✅" if os.path.exists(pdftotext) else f"❌ {pdftotext} 없음"
    else:
        checks["pdftotext"] = "❌ .env에 POPPLER_PATH 설정 필요"

    # Node.js
    try:
        proc = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=5)
        checks["nodejs"] = f"✅ {proc.stdout.strip()}"
    except Exception:
        checks["nodejs"] = "❌ Node.js 없음"

    # docx 모듈
    docx_path = BASE / "node_modules" / "docx"
    checks["docx_module"] = "✅" if docx_path.exists() else "❌ npm install 필요"

    # python-pptx
    try:
        import pptx
        checks["python_pptx"] = f"✅ {pptx.__version__}"
    except ImportError:
        checks["python_pptx"] = "❌ pip install python-pptx 필요"

    return checks
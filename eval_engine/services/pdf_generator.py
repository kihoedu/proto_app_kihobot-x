"""
서버사이드 PDF 생성 — reportlab 버전
Windows/Linux 모두 호환
"""
import re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── 폰트 등록 ─────────────────────────────────────────────────
def _register_fonts():
    candidates_reg = [
        r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    candidates_bold = [
        r"C:\Windows\Fonts\malgunbd.ttf",
        r"C:\Windows\Fonts\NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    ]
    reg  = next((c for c in candidates_reg  if Path(c).exists()), None)
    bold = next((c for c in candidates_bold if Path(c).exists()), None)
    if reg:
        try:
            pdfmetrics.registerFont(TTFont("KR",   reg))
            pdfmetrics.registerFont(TTFont("KR-B", bold if bold else reg))
            return True
        except Exception:
            pass
    return False

_HAS_KR = _register_fonts()
F  = "KR"   if _HAS_KR else "Helvetica"
FB = "KR-B" if _HAS_KR else "Helvetica-Bold"

# ── 색상 ──────────────────────────────────────────────────────
CP  = colors.HexColor("#534AB7")
CD  = colors.HexColor("#1a1a18")
CG  = colors.HexColor("#888780")
CL  = colors.HexColor("#f7f6f3")
CB  = colors.HexColor("#e2e0d9")
CG2 = colors.HexColor("#1D9E75")
CO  = colors.HexColor("#EF9F27")
CI  = colors.HexColor("#fafaf8")
CT  = colors.HexColor("#EEEDFE")

def _s(name, **kw):
    d = dict(fontName=F, fontSize=11, leading=19, textColor=CD,
             spaceAfter=4, alignment=TA_JUSTIFY)
    d.update(kw)
    return ParagraphStyle(name, **d)

def _e(t):
    if not t: return ""
    t = str(t)
    filled = "❶❷❸❹❺❻❼❽❾❿⑪⑫⑬⑭⑮"
    hollow = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
    for f, h in zip(filled, hollow):
        t = t.replace(f, h)
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _fmt_imp(text):
    if not text: return []
    parts = text.split("\n\n")
    cur, items = "", []
    for p in parts:
        p = p.strip()
        if not p: continue
        if re.match(r"^\(\d+\)", p):
            if cur.strip(): items.append(cur.strip())
            cur = p
        else:
            cur += "\n" + p if cur else p
    if cur.strip(): items.append(cur.strip())
    if not items: items = [text]

    result = []
    for item in items:
        ls     = item.split("\n")
        header = ls[0]
        body   = "\n".join(ls[1:])
        body = re.sub(r"\s*수정\s*전:\s*",        "\n__before__ ", body)
        body = re.sub(r"\s*수정\s*후:\s*",        "\n__after__ ",  body)
        body = re.sub(r"\s*→\s*수정\s*이유:\s*",  "\n__reason__ ", body)

        flows = [Paragraph(f'<font color="#534AB7"><b>{_e(header)}</b></font>',
                           _s("ih", fontSize=11, leading=17))]
        flows.append(Spacer(1, 3))
        for line in body.split("\n"):
            line = line.strip()
            if not line: continue
            if line.startswith("__before__"):
                t = line[10:].strip()
                flows.append(Paragraph(
                    f'<font color="#854F0B"><b>수정 전</b></font> {_e(t)}',
                    _s("ib", fontSize=11, leading=17)))
            elif line.startswith("__after__"):
                t = line[9:].strip()
                flows.append(Paragraph(
                    f'<font color="#0F6E56"><b>수정 후</b></font> {_e(t)}',
                    _s("ia", fontSize=11, leading=17)))
            elif line.startswith("__reason__"):
                t = line[10:].strip()
                flows.append(Paragraph(
                    f'<font color="#666666">→ 수정 이유</font> {_e(t)}',
                    _s("ir", fontSize=10, leading=16, textColor=colors.HexColor("#666666"))))
            else:
                flows.append(Paragraph(_e(line), _s("il", fontSize=11, leading=17)))

        box = Table([[flows]], colWidths=[155*mm])
        box.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), CI),
            ("BOX",           (0,0),(-1,-1), 0.5, CB),
            ("TOPPADDING",    (0,0),(-1,-1), 8),
            ("BOTTOMPADDING", (0,0),(-1,-1), 8),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
            ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ]))
        result.append(KeepTogether([box, Spacer(1, 8)]))
    return result


def generate_pdf(report: dict, output_path: str) -> str:
    sname  = report.get("student_name", "") or ""
    aname  = report.get("academy_name", "") or ""
    sdate  = (report.get("created_at") or "")[:10]
    items  = report.get("items", [])
    scores = [i.get("score") for i in items if i.get("score") is not None]
    avg    = round(sum(scores) / len(scores), 1) if scores else None

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=22*mm, rightMargin=22*mm,
        topMargin=20*mm, bottomMargin=20*mm,
        title=f"논술 성적 리포트 - {sname}",
    )
    story = []

    # ══════════════════════════════════════════
    # 표지
    # ══════════════════════════════════════════
    story.append(Spacer(1, 8*mm))

    # ① 다크 헤더 박스
    ch = Table([[
        [Paragraph(
            '<font color="#888780">BAKHIHO MATRIX ESSAY EVALUATION</font>',
            _s("ce", fontSize=9, leading=14, textColor=CG)),
         Spacer(1, 8),
         Paragraph(
            "[박기호논술]<br/>성적 리포트",
            _s("ct", fontName=FB, fontSize=28, leading=36, textColor=colors.white))]
    ]], colWidths=[166*mm])
    ch.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), CD),
        ("TOPPADDING",    (0,0),(-1,-1), 26),
        ("BOTTOMPADDING", (0,0),(-1,-1), 26),
        ("LEFTPADDING",   (0,0),(-1,-1), 22),
        ("RIGHTPADDING",  (0,0),(-1,-1), 22),
    ]))
    story.append(ch)

    # ② 컬러 바 (보라 / 초록 / 주황)
    bar = Table([["", "", ""]], colWidths=[99.6*mm, 33.2*mm, 33.2*mm], rowHeights=[5])
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(0,0), CP),
        ("BACKGROUND", (1,0),(1,0), CG2),
        ("BACKGROUND", (2,0),(2,0), CO),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
    ]))
    story.append(bar)

    # ③ 학생 정보 카드  ← 기존 코드에서 story.append(wrap) 누락되어 있었음
    info_rows = []
    if aname:
        info_rows.append(["학원명", aname])
    info_rows.append(["학생명", sname if sname else "-"])
    info_rows.append(["제출일", sdate if sdate else "-"])

    it = Table(info_rows, colWidths=[30*mm, 120*mm])
    it.setStyle(TableStyle([
        ("FONTNAME",        (0,0), (-1,-1), F),
        ("TEXTCOLOR",       (0,0), (0,-1),  CG),
        ("FONTNAME",        (1,0), (1,-1),  FB),
        ("FONTSIZE",        (0,0), (-1,-1), 12),
        ("TOPPADDING",      (0,0), (-1,-1), 10),
        ("BOTTOMPADDING",   (0,0), (-1,-1), 10),
        ("LEFTPADDING",     (0,0), (-1,-1), 0),
        ("LINEBELOW",       (0,0), (-1,-2), 0.5, CB),
    ]))

    # STUDENT INFORMATION 헤더 + 정보 테이블을 하나의 카드로 감싸기
    si_label = Paragraph(
        '<font color="#888780">STUDENT INFORMATION</font>',
        _s("si", fontName=F, fontSize=9, leading=14,
           textColor=CG, spaceAfter=12, alignment=TA_JUSTIFY),
    )
    wrap = Table([[
        [si_label, Spacer(1, 10), it]
    ]], colWidths=[166*mm])
    wrap.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.5, CB),
        ("TOPPADDING",    (0,0),(-1,-1), 20),
        ("BOTTOMPADDING", (0,0),(-1,-1), 22),
        ("LEFTPADDING",   (0,0),(-1,-1), 22),
        ("RIGHTPADDING",  (0,0),(-1,-1), 22),
    ]))
    story.append(wrap)          # ← 핵심: 이 줄이 빠져 있었음

    # ④ 표지 하단 여백 + 페이지 구분
    story.append(Spacer(1, 12*mm))

    # Confidential 푸터 (표지 하단)
    footer_rows = [
        ["Confidential", "● ● ●"]
    ]
    ft = Table(footer_rows, colWidths=[83*mm, 83*mm])
    ft.setStyle(TableStyle([
        ("FONTNAME",    (0,0),(-1,-1), F),
        ("FONTSIZE",    (0,0),(-1,-1), 9),
        ("TEXTCOLOR",   (0,0),(-1,-1), CG),
        ("ALIGN",       (1,0),(1,-1),  "RIGHT"),
        ("TOPPADDING",  (0,0),(-1,-1), 0),
        ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))
    story.append(ft)
    story.append(PageBreak())

    # ══════════════════════════════════════════
    # 성적 요약
    # ══════════════════════════════════════════
    story.append(Paragraph("문항별 성적 분석",
        _s("h1", fontName=FB, fontSize=13, textColor=CP, spaceAfter=8)))
    story.append(HRFlowable(width="100%", thickness=2, color=CP, spaceAfter=12))

    sd = [["문항", "논제 유형", "성적 (100점 만점)"]]
    for item in items:
        s = item.get("score")
        sd.append([
            f"문항 {item.get('item_number', '')}",
            item.get("problem_type", "") or "-",
            f"{s}점" if s is not None else "-",
        ])
    if avg is not None:
        sd.append(["", "평균 점수", f"{avg}점"])

    st = Table(sd, colWidths=[40*mm, 80*mm, 46*mm])
    st.setStyle(TableStyle([
        ("FONTNAME",      (0,0),(-1,-1), F),
        ("FONTNAME",      (0,0),(-1,0),  FB),
        ("FONTSIZE",      (0,0),(-1,-1), 11),
        ("BACKGROUND",    (0,0),(-1,0),  CP),
        ("TEXTCOLOR",     (0,0),(-1,0),  colors.white),
        ("BACKGROUND",    (0,-1),(-1,-1),colors.HexColor("#f1f0ec")),
        ("FONTNAME",      (0,-1),(-1,-1),FB),
        ("ALIGN",         (0,0),(-1,-1), "CENTER"),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("GRID",          (0,0),(-1,-1), 0.5, CB),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
    ]))
    story.append(st)
    story.append(PageBreak())

    # ══════════════════════════════════════════
    # 문항별 첨삭
    # ══════════════════════════════════════════
    fbs = _s("fb", fontName=F, fontSize=11, leading=20)
    for idx, item in enumerate(items):
        final = item.get("teacher_result") or item.get("llm_result") or {}
        if not final:
            continue

        sc     = item.get("score")
        sc_str = f"  ({sc}점)" if sc is not None else ""
        pt     = item.get("problem_type", "") or ""
        title  = f"문항 {item.get('item_number', '')} - {pt}{sc_str}"

        flows = []
        hdr = Table([[Paragraph(title, _s("ih", fontName=FB, fontSize=13))]],
                    colWidths=[166*mm])
        hdr.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#f1f0ec")),
            ("LEFTPADDING",   (0,0),(-1,-1), 12),
            ("RIGHTPADDING",  (0,0),(-1,-1), 12),
            ("TOPPADDING",    (0,0),(-1,-1), 9),
            ("BOTTOMPADDING", (0,0),(-1,-1), 9),
            ("LINEBEFORE",    (0,0),(0,-1),  4, CP),
        ]))
        flows.append(hdr)
        flows.append(Spacer(1, 12))

        # 학생 답안
        flows.append(Paragraph("학생 제출 답안",
            _s("sh", fontName=FB, fontSize=12, textColor=CP, spaceAfter=5)))
        flows.append(HRFlowable(width="100%", thickness=1.5, color=CP, spaceAfter=8))
        ans   = final.get("numbered_text", "").strip() or item.get("ocr_text", "").strip() or ""
        paras = ans.replace("\n\n", "|||").replace("\n", " ").split("|||")
        ap    = []
        for p in paras:
            if p.strip():
                ap.append(Paragraph(_e(p.strip()), _s("ap", fontName=F, fontSize=11, leading=20)))
                ap.append(Spacer(1, 3))
        abox = Table([[ap]], colWidths=[166*mm])
        abox.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), CL),
            ("BOX",           (0,0),(-1,-1), 0.5, CB),
            ("TOPPADDING",    (0,0),(-1,-1), 10),
            ("BOTTOMPADDING", (0,0),(-1,-1), 10),
            ("LEFTPADDING",   (0,0),(-1,-1), 12),
            ("RIGHTPADDING",  (0,0),(-1,-1), 12),
        ]))
        flows.append(abox)
        flows.append(Spacer(1, 16))

        # 세부 첨삭
        flows.append(Paragraph("세부 첨삭",
            _s("sh2", fontName=FB, fontSize=12, textColor=CP, spaceAfter=5)))
        flows.append(HRFlowable(width="100%", thickness=1.5, color=CP, spaceAfter=10))

        def tag(label):
            return Paragraph(
                f'<font color="#534AB7"><b> {label} </b></font>',
                _s("tg", fontSize=10, fontName=FB, backColor=CT,
                   borderPadding=3, spaceAfter=5))

        if final.get("strengths"):
            flows.append(KeepTogether([tag("장점"),
                Paragraph(_e(final["strengths"]), fbs), Spacer(1, 10)]))
        if final.get("weaknesses"):
            flows.append(KeepTogether([tag("단점"),
                Paragraph(_e(final["weaknesses"]), fbs), Spacer(1, 10)]))
        if final.get("improvements"):
            flows.append(tag("보완할 부분"))
            flows += _fmt_imp(final["improvements"])
            flows.append(Spacer(1, 4))
        if final.get("summary"):
            flows.append(KeepTogether([tag("총평"),
                Paragraph(_e(final["summary"]), fbs), Spacer(1, 10)]))

        flows.append(Spacer(1, 8))
        flows.append(HRFlowable(width="100%", thickness=0.5, color=CB))
        flows.append(Paragraph(
            aname,
            _s("ft", fontSize=10, textColor=CG, alignment=TA_CENTER, spaceBefore=5)))

        story += flows
        if idx < len(items) - 1:
            story.append(PageBreak())

    doc.build(story)
    return output_path

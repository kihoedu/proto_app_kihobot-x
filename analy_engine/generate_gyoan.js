const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, TabStopType
} = require("docx");

// ============================================================
// 상수
// ============================================================
const FONT = "맑은 고딕";
const PAGE_WIDTH = 11906;
const PAGE_HEIGHT = 16838;
const M = 1134;                     // 여백 (2cm)
const CW = PAGE_WIDTH - M - M;     // 콘텐츠 너비 ~9638

const thinB = { style: BorderStyle.SINGLE, size: 1, color: "999999" };
const borders = { top: thinB, bottom: thinB, left: thinB, right: thinB };
const cellMg = { top: 60, bottom: 60, left: 100, right: 100 };

// ============================================================
// 헬퍼 함수
// ============================================================
function p(text, opts = {}) {
  const runs = [];
  const lines = text.split("\n");
  lines.forEach((line, i) => {
    runs.push(new TextRun({
      text: line, font: FONT,
      size: opts.size || 20,
      bold: opts.bold || false,
      color: opts.color || "000000"
    }));
    if (i < lines.length - 1) {
      runs.push(new TextRun({ break: 1, font: FONT, size: opts.size || 20 }));
    }
  });
  return new Paragraph({
    children: runs,
    alignment: opts.alignment || AlignmentType.BOTH,
    spacing: {
      after: opts.spacingAfter !== undefined ? opts.spacingAfter : 80,
      before: opts.spacingBefore || 0,
      line: opts.lineSpacing || 276,
    },
    indent: opts.indent ? { firstLine: opts.indent } : undefined,
  });
}

/** 연파란 배경 박스 헤딩 (1부. 문제, 2부. 해설) */
function boxHeading(text, size = 32) {
  const bdr = { style: BorderStyle.SINGLE, size: 6, color: "888888" };
  const no = { style: BorderStyle.NONE, size: 0 };
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [CW],
    rows: [new TableRow({ children: [new TableCell({
      borders: { top: bdr, bottom: bdr, left: no, right: no },
      width: { size: CW, type: WidthType.DXA },
      shading: { fill: "D6E4F0", type: ShadingType.CLEAR },
      margins: { top: 100, bottom: 100, left: 200, right: 200 },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({
        children: [new TextRun({ text, font: FONT, size, bold: true })],
        alignment: AlignmentType.CENTER
      })]
    })] })]
  });
}

/** 문제 번호 박스 (테두리만, 배경 없음) */
function problemBox(text, size = 26) {
  const bdr = { style: BorderStyle.SINGLE, size: 6, color: "888888" };
  const no = { style: BorderStyle.NONE, size: 0 };
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [CW],
    rows: [new TableRow({ children: [new TableCell({
      borders: { top: bdr, bottom: bdr, left: no, right: no },
      width: { size: CW, type: WidthType.DXA },
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({
        children: [new TextRun({ text, font: FONT, size, bold: true })],
        alignment: AlignmentType.CENTER
      })]
    })] })]
  });
}

/** ▣ 섹션 라벨 */
function sectionLabel(text) {
  return new Paragraph({
    children: [
      new TextRun({ text: "▣  ", font: FONT, size: 22, bold: true }),
      new TextRun({ text, font: FONT, size: 22, bold: true })
    ],
    spacing: { before: 240, after: 160 },
  });
}

// ============================================================
// 1부. 문제
// ============================================================
function buildPart1(sets, m) {
  const ch = [];

  // ── 표지 ──
  const titleText = `${m.university} 파이널`;
  // 대학명 길이에 따라 폰트 크기 조절 (한 줄에 들어가도록)
  let titleSize = 96;
  if (titleText.length > 8) titleSize = 80;
  if (titleText.length > 10) titleSize = 72;

  ch.push(new Paragraph({ spacing: { before: 4000 } }));
  ch.push(new Paragraph({
    children: [new TextRun({ text: titleText, font: FONT, size: titleSize })],
    alignment: AlignmentType.CENTER,
    spacing: { before: 200, after: 200 },
    border: {
      top: { style: BorderStyle.SINGLE, size: 12, color: "000000", space: 8 },
      bottom: { style: BorderStyle.SINGLE, size: 12, color: "000000", space: 8 }
    }
  }));
  ch.push(new Paragraph({
    children: [new TextRun({ text: `${m.year} 기출`, font: FONT, size: 60, bold: true })],
    alignment: AlignmentType.CENTER,
    spacing: { before: 1200, after: 80 }
  }));
  ch.push(new Paragraph({
    children: [new TextRun({ text: `-${m.subtitle}-`, font: FONT, size: 60 })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 400, line: 240 }
  }));
  ch.push(new Paragraph({ children: [new PageBreak()] }));

  // ── 1부 제목 ──
  ch.push(boxHeading("1부. 문제"));

  for (const set of sets) {
    if (set.number > 1) {
      ch.push(new Paragraph({ children: [new PageBreak()] }));
    }
    ch.push(problemBox(`[문제 ${set.number}]`));

    // 첫 문제에만 시험 시간 표시
    if (set.number === 1) {
      ch.push(new Paragraph({ spacing: { after: 120 } }));
      ch.push(p(`- ${m.university} ${m.year} 기출 -  ※시험 시간 ${m.examTime}분`, {
        alignment: AlignmentType.RIGHT, size: 18, spacingAfter: 300
      }));
    }

    // 지시문
    ch.push(new Paragraph({ spacing: { after: 160 } }));
    ch.push(p(set.instructions || "※ 다음 제시문을 읽고 물음에 답하시오.", {
      bold: true, spacingAfter: 200
    }));

    // 제시문들
    for (const ps of (set.passages || [])) {
      ch.push(p(ps.label, { bold: true, size: 21, spacingAfter: 40 }));

      // 본문 (줄마다 들여쓰기 + 양쪽정렬)
      for (const para of ps.text.split("\n")) {
        ch.push(p(para, { indent: 300, lineSpacing: 276, spacingAfter: 40 }));
      }

      // 출처 (저자, 작품명)
      if (ps.source) {
        for (const srcLine of ps.source.split("\n")) {
          const isFn = srcLine.startsWith("*");
          ch.push(p(srcLine, {
            size: 18,
            alignment: isFn ? AlignmentType.LEFT : AlignmentType.RIGHT,
            spacingAfter: 20
          }));
        }
      }

      // 교과서명
      if (ps.textbook) {
        ch.push(p(`-${ps.textbook}`, {
          size: 18, alignment: AlignmentType.RIGHT, spacingAfter: 200
        }));
      }
    }

    // 문제 본문 (볼드)
    if (set.question) {
      ch.push(new Paragraph({
        children: [
          new TextRun({ text: `[문제 ${set.number}] `, font: FONT, size: 20, bold: true }),
          new TextRun({ text: set.question.text || "", font: FONT, size: 20, bold: true }),
          new TextRun({
            text: ` <${set.question.wordCount || ""}> [${set.question.points || ""}점]`,
            font: FONT, size: 20, bold: true
          }),
        ],
        alignment: AlignmentType.BOTH,
        spacing: { before: 120, after: 300, line: 276 },
        indent: { firstLine: 300 },
      }));
    }
  }
  return ch;
}

// ============================================================
// 2부. 해설
// ============================================================

/** 제시문 해설 테이블 (2열: 제시문 원문 | 강사 메모) */
function buildCommentaryTable(passages) {
  const c1 = Math.round(CW * 0.65);
  const c2 = CW - c1;
  return new Table({
    width: { size: CW, type: WidthType.DXA },
    columnWidths: [c1, c2],
    rows: passages.map(ps => new TableRow({
      children: [
        new TableCell({
          borders, width: { size: c1, type: WidthType.DXA }, margins: cellMg,
          children: [
            new Paragraph({
              children: [new TextRun({ text: ps.label, font: FONT, size: 19, bold: true })],
              spacing: { after: 60 }
            }),
            ...ps.text.split("\n").map(l => {
              const isSource = l.startsWith("-『") || l.startsWith("- 『") || l.startsWith("(");
              const isFootnote = l.startsWith("*");
              return new Paragraph({
                children: [new TextRun({ text: l, font: FONT, size: 18 })],
                spacing: { after: 40, line: 276 },
                alignment: (isSource && !isFootnote) ? AlignmentType.RIGHT : AlignmentType.BOTH,
                indent: (!isSource && !isFootnote) ? { firstLine: 300 } : undefined
              });
            })
          ]
        }),
        new TableCell({
          borders, width: { size: c2, type: WidthType.DXA }, margins: cellMg,
          children: [new Paragraph({
            children: [new TextRun({ text: "", font: FONT, size: 18 })]
          })]
        })
      ]
    }))
  });
}

/** 채점 등급 테이블 */
function buildGradeTable(table) {
  if (!table || table.length === 0) return [];
  const gc = 600, cc = 500, dc = CW - gc - cc;
  const hdr = (t) => new Paragraph({
    children: [new TextRun({ text: t, font: FONT, size: 18, bold: true })],
    alignment: AlignmentType.CENTER
  });
  return [new Table({
    width: { size: CW, type: WidthType.DXA },
    columnWidths: [gc, cc, dc],
    rows: [
      new TableRow({ children: [
        new TableCell({ borders, width: { size: gc, type: WidthType.DXA }, shading: { fill: "E8E8E8", type: ShadingType.CLEAR }, margins: cellMg, verticalAlign: VerticalAlign.CENTER, children: [hdr("등급")] }),
        new TableCell({ borders, width: { size: cc, type: WidthType.DXA }, shading: { fill: "E8E8E8", type: ShadingType.CLEAR }, margins: cellMg, verticalAlign: VerticalAlign.CENTER, children: [hdr("")] }),
        new TableCell({ borders, width: { size: dc, type: WidthType.DXA }, shading: { fill: "E8E8E8", type: ShadingType.CLEAR }, margins: cellMg, verticalAlign: VerticalAlign.CENTER, children: [hdr("기준")] })
      ] }),
      ...table.map(r => new TableRow({ children: [
        new TableCell({ borders, width: { size: gc, type: WidthType.DXA }, margins: cellMg, verticalAlign: VerticalAlign.CENTER,
          children: [new Paragraph({ children: [new TextRun({ text: r.grade || "", font: FONT, size: 18, bold: true })], alignment: AlignmentType.CENTER })]
        }),
        new TableCell({ borders, width: { size: cc, type: WidthType.DXA }, margins: cellMg, verticalAlign: VerticalAlign.CENTER,
          children: [new Paragraph({ children: [new TextRun({ text: r.code || "", font: FONT, size: 18, bold: true })], alignment: AlignmentType.CENTER })]
        }),
        new TableCell({ borders, width: { size: dc, type: WidthType.DXA }, margins: cellMg,
          children: [new Paragraph({ children: [new TextRun({ text: r.desc || "", font: FONT, size: 18 })], spacing: { line: 276 } })]
        })
      ] }))
    ]
  })];
}

function buildPart2(sets, m) {
  const ch = [];
  ch.push(new Paragraph({ children: [new PageBreak()] }));
  ch.push(boxHeading("2부. 해설"));

  // ── 1) 제시문 해설 테이블 (전체 문제 통합) ──
  const allCommentary = [];
  for (const set of sets) {
    const commentary = set.commentary || [];
    if (commentary.length > 0) {
      allCommentary.push(...commentary);
    }
  }

  if (allCommentary.length > 0) {
    // 문제 범위 표시 (예: "문제 1~3")
    const nums = sets.map(s => s.number);
    const rangeStr = nums.length === 1
      ? `문제 ${nums[0]}`
      : `문제 ${nums[0]}~${nums[nums.length - 1]}`;
    ch.push(sectionLabel(`제시문 해설 [${rangeStr}]`));
    ch.push(buildCommentaryTable(allCommentary));
  }

  // ── 2) 문제별: 출제의도 → 문제해설 → 매트릭스 → 예시답안 → 채점기준 ──
  for (const set of sets) {
    ch.push(new Paragraph({ children: [new PageBreak()] }));
    ch.push(problemBox(`[문제 ${set.number}]`));

    // 출제의도
    if (set["출제의도"]) {
      ch.push(sectionLabel(`출제의도 [문제 ${set.number}]`));
      for (const l of set["출제의도"].split("\n")) {
        ch.push(p(l, { indent: 300, lineSpacing: 276, spacingAfter: 40 }));
      }
    }

    // 문제해설
    if (set["문제해설"]) {
      ch.push(sectionLabel(`문제해설 [문제 ${set.number}]`));
      for (const l of set["문제해설"].split("\n")) {
        ch.push(p(l, { indent: 300, lineSpacing: 276, spacingAfter: 40 }));
      }
    }

    // 매트릭스 분석
    ch.push(new Paragraph({ children: [new PageBreak()] }));
    ch.push(sectionLabel(`매트릭스 분석 [문제 ${set.number}]`));
    if (set.question) {
      ch.push(p(
        `[문제 ${set.number}] ${set.question.text || ""} <${set.question.wordCount || ""}> [${set.question.points || ""}점]`,
        { bold: true, size: 19, spacingAfter: 200 }
      ));
    }
    ch.push(p("(매트릭스 분석표 - 강사 작성 영역)", {
      size: 18, color: "999999", alignment: AlignmentType.CENTER, spacingAfter: 200
    }));

    // 예시답안 (매트릭스 + 대학측)
    ch.push(new Paragraph({ children: [new PageBreak()] }));
    ch.push(sectionLabel(`예시답안 [문제 ${set.number}]`));

    ch.push(p("[매트릭스 예시답안]", { bold: true, spacingAfter: 80 }));
    ch.push(p("(강사 작성 영역)", {
      size: 18, color: "999999", alignment: AlignmentType.CENTER, spacingAfter: 200
    }));

    if (set.sampleAnswer) {
      ch.push(new Paragraph({ spacing: { after: 120 } }));
      ch.push(p("[대학 측 예시답안]", { bold: true, spacingAfter: 80 }));
      for (const l of set.sampleAnswer.split("\n")) {
        ch.push(p(l, { indent: 200, lineSpacing: 300 }));
      }
    }

    // 채점 기준
    if (set.rubric || (set.rubricTable && set.rubricTable.length > 0)) {
      ch.push(new Paragraph({ children: [new PageBreak()] }));
      ch.push(sectionLabel(`채점 기준 [문제 ${set.number}]`));
      ch.push(p("[대학측 채점 기준]", { bold: true, spacingAfter: 80 }));

      if (set.rubric) {
        for (const l of set.rubric.split("\n")) {
          ch.push(p(l, { size: 19, spacingAfter: 40 }));
        }
        ch.push(new Paragraph({ spacing: { after: 120 } }));
      }

      ch.push(...buildGradeTable(set.rubricTable));
    }

    ch.push(new Paragraph({ spacing: { after: 300 } }));
  }

  return ch;
}

// ============================================================
// MAIN
// ============================================================
async function main() {
  const outputFile = process.argv[2];
  const dataFile = process.argv[3];

  if (!dataFile) {
    console.error("사용법: node generate_gyoan.js <출력.docx> <데이터.json>");
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(path.resolve(dataFile), "utf-8"));
  const m = data.meta;
  const sets = data.problemSets;

  const doc = new Document({
    styles: { default: { document: { run: { font: FONT, size: 20 } } } },
    sections: [{
      properties: {
        page: {
          size: { width: PAGE_WIDTH, height: PAGE_HEIGHT },
          margin: { top: M, bottom: M, left: M, right: M }
        }
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            children: [
              new TextRun({ text: "[ EOLE 논술 연구소 ]", font: FONT, size: 20, color: "888888" }),
              new TextRun({ text: "\t", font: FONT, size: 20 }),
              new TextRun({ text: "www.eole.co.kr", font: FONT, size: 20, color: "888888" })
            ],
            tabStops: [{ type: TabStopType.RIGHT, position: CW }]
          })]
        })
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            children: [
              new TextRun({ text: `${m.university} ${m.year} 기출 논술 매트릭스`, font: FONT, size: 16, color: "888888" }),
              new TextRun({ text: "\t- ", font: FONT, size: 16, color: "888888" }),
              new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "888888" }),
              new TextRun({ text: " -", font: FONT, size: 16, color: "888888" })
            ],
            tabStops: [{ type: TabStopType.RIGHT, position: CW }]
          })]
        })
      },
      children: [
        ...buildPart1(sets, m),
        ...buildPart2(sets, m),
      ]
    }]
  });

  const buf = await Packer.toBuffer(doc);
  const defaultName = `${m.university}_${m.year}_${(m.track || "").replace(/\s+/g, "")}_교안.docx`;
  const out = outputFile || defaultName;
  fs.writeFileSync(out, buf);
  console.log(`✅ ${out} (${buf.length.toLocaleString()} bytes)`);
}

main().catch(err => {
  console.error("❌ 오류:", err.message);
  process.exit(1);
});
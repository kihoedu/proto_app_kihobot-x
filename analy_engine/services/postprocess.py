#!/usr/bin/env python3
"""
DOCX 후처리: wordWrap=0 패치 (HWP 스타일 양쪽정렬)
generate_gyoan.js 실행 후 이 스크립트로 후처리
"""
import sys, os, re, zipfile, shutil, tempfile


def patch_docx(input_path: str, output_path: str = None):
    if not output_path:
        output_path = input_path

    with tempfile.TemporaryDirectory() as tmp:
        # 압축 해제
        with zipfile.ZipFile(input_path, "r") as z:
            z.extractall(tmp)

        # document.xml 패치
        doc_xml = os.path.join(tmp, "word", "document.xml")
        with open(doc_xml, "r", encoding="utf-8") as f:
            xml = f.read()

        def add_wrap(m):
            c = m.group(1)
            if "<w:wordWrap" not in c:
                c = '<w:wordWrap w:val="0"/><w:autoSpaceDE w:val="0"/><w:autoSpaceDN w:val="0"/>' + c
            return f"<w:pPr>{c}</w:pPr>"

        xml = re.sub(r"<w:pPr>(.*?)</w:pPr>", add_wrap, xml, flags=re.DOTALL)

        with open(doc_xml, "w", encoding="utf-8") as f:
            f.write(xml)

        # 재압축
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(tmp):
                for file in files:
                    abs_path = os.path.join(root, file)
                    arc_name = os.path.relpath(abs_path, tmp)
                    z.write(abs_path, arc_name)

    print(f"✅ 패치 완료: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python backend/postprocess.py <DOCX경로> [출력경로]")
        sys.exit(1)
    patch_docx(sys.argv[1], sys.argv[2] if len(sys.argv) >= 3 else None)

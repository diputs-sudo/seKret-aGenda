from zipfile import ZipFile

from backend.parser.docx import _read_paragraphs


def test_read_paragraphs_detects_direct_shading_and_style_highlights(tmp_path):
    docx_path = tmp_path / "cards.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:r>
        <w:rPr>
          <w:highlight w:val="yellow"/>
          <w:sz w:val="24"/>
          <w:b/>
          <w:u w:val="single"/>
        </w:rPr>
        <w:t>direct highlight</w:t>
      </w:r>
    </w:p>
    <w:p>
      <w:r>
        <w:rPr><w:shd w:fill="00FF00"/></w:rPr>
        <w:t>shaded highlight</w:t>
      </w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="HighlightedParagraph"/></w:pPr>
      <w:r><w:t>paragraph style highlight</w:t></w:r>
    </w:p>
    <w:p>
      <w:r>
        <w:rPr><w:rStyle w:val="HighlightedCharacter"/></w:rPr>
        <w:t>character style highlight</w:t>
      </w:r>
    </w:p>
  </w:body>
</w:document>
"""
    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="HighlightedParagraph">
    <w:rPr><w:highlight w:val="yellow"/></w:rPr>
  </w:style>
  <w:style w:type="character" w:styleId="HighlightedCharacter">
    <w:rPr><w:highlight w:val="yellow"/></w:rPr>
  </w:style>
</w:styles>
"""

    with ZipFile(docx_path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/styles.xml", styles_xml)

    paragraphs = _read_paragraphs(docx_path)

    assert [paragraph.runs[0].highlight for paragraph in paragraphs] == [
        "yellow",
        "00ff00",
        "style",
        "style",
    ]
    assert paragraphs[0].runs[0].font_size == 12.0
    assert paragraphs[0].runs[0].bold is True
    assert paragraphs[0].runs[0].underline is True

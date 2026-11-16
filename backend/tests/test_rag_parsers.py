"""B6 解析层测试：真实生成 md/html/docx/xlsx/pdf 字节，再用统一解析器解析回来断言。

红线：不用固定假对象冒充解析结果；断言全部基于 parse_document/chunk_document 的真实输出。
"""

from __future__ import annotations

import io
import math

import openpyxl
import pymupdf
import pytest
import docx as docx_lib

from app.rag.chunker import chunk_document
from app.rag.parsers import parse_document
from app.rag.types import Chunk, ParsedDocument


# ---------------------------------------------------------------- md

def test_md_headings_paragraphs_and_code_block():
    md = (
        "# 项目总览\n"
        "## 架构设计\n"
        "本段介绍架构，\n"
        "包含两行文字。\n"
        "\n"
        "```python\n"
        "print('hello')\n"
        "x = 42\n"
        "```\n"
        "\n"
        "代码块之后的普通段落。\n"
        "### 细节\n"
        "尾部段落内容。\n"
    ).encode("utf-8")

    parsed = parse_document("设计说明.md", md)
    assert isinstance(parsed, ParsedDocument)
    assert parsed.title == "项目总览"  # 首个 heading 作为更好的标题
    headings = [b for b in parsed.blocks if b.type == "heading"]
    assert [(h.text, h.level) for h in headings] == [
        ("项目总览", 1),
        ("架构设计", 2),
        ("细节", 3),
    ]
    paragraphs = [b.text for b in parsed.blocks if b.type == "paragraph"]
    assert any("本段介绍架构" in t and "包含两行文字" in t for t in paragraphs)
    # 代码块整体为一个 paragraph，且保留内部换行
    code_blocks = [t for t in paragraphs if "print('hello')" in t]
    assert len(code_blocks) == 1
    assert "x = 42" in code_blocks[0] and "\n" in code_blocks[0]
    assert any(t.startswith("代码块之后的普通段落") for t in paragraphs)


# ---------------------------------------------------------------- txt

def test_txt_blank_line_paragraphs():
    raw = "第一段第一行\n第一段第二行\n\n第二段\n\n\n第三段内容".encode("utf-8")
    parsed = parse_document("notes.txt", raw)
    assert parsed.title == "notes"
    paras = [b.text for b in parsed.blocks if b.type == "paragraph"]
    assert len(paras) == 3
    assert paras[0] == "第一段第一行\n第一段第二行"
    assert paras[1] == "第二段"
    assert paras[2] == "第三段内容"


# ---------------------------------------------------------------- html

def test_html_title_heading_paragraph_table_and_script_dropped():
    html = (
        "<html><head><title>季度报告</title></head><body>"
        "<h1>第一章 业绩</h1>"
        "<p>营收同比增长。</p>"
        "<script>alert('xss'); var secret = 1;</script>"
        "<style>body { color: red; }</style>"
        "<p>成本保持稳定。</p>"
        "<table><tr><th>指标</th><th>数值</th></tr>"
        "<tr><td>营收</td><td>100</td></tr></table>"
        "</body></html>"
    ).encode("utf-8")

    parsed = parse_document("report.html", html)
    assert parsed.title == "季度报告"  # <title> 优先于文件名
    headings = [b for b in parsed.blocks if b.type == "heading"]
    assert [(h.text, h.level) for h in headings] == [("第一章 业绩", 1)]
    paragraphs = [b.text for b in parsed.blocks if b.type == "paragraph"]
    assert "营收同比增长。" in paragraphs
    assert "成本保持稳定。" in paragraphs
    tables = [b for b in parsed.blocks if b.type == "table"]
    assert len(tables) == 1
    assert tables[0].rows == [["指标", "数值"], ["营收", "100"]]
    # script/style 内容必须被丢弃
    assert "alert" not in parsed.text and "secret" not in parsed.text
    assert "color" not in parsed.text


# ---------------------------------------------------------------- docx

def test_docx_roundtrip_heading_paragraph_table():
    document = docx_lib.Document()
    document.add_heading("项目说明", 1)
    document.add_paragraph("这是正文段落，用于验证 docx 解析。")
    document.add_heading("数据表", 2)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "字段"
    table.cell(0, 1).text = "值"
    table.cell(1, 0).text = "name"
    table.cell(1, 1).text = "EvoCode"
    buf = io.BytesIO()
    document.save(buf)

    parsed = parse_document("demo.docx", buf.getvalue())
    assert parsed.title == "demo"
    headings = [b for b in parsed.blocks if b.type == "heading"]
    assert [(h.text, h.level) for h in headings] == [("项目说明", 1), ("数据表", 2)]
    assert any("这是正文段落" in b.text for b in parsed.blocks if b.type == "paragraph")
    tables = [b for b in parsed.blocks if b.type == "table"]
    assert len(tables) == 1
    assert tables[0].rows == [["字段", "值"], ["name", "EvoCode"]]


# ---------------------------------------------------------------- xlsx

def test_xlsx_two_sheets_tables_with_rows_and_empty_row_skipped():
    workbook = openpyxl.Workbook()
    ws1 = workbook.active
    ws1.title = "销售"
    ws1.append(["月份", "金额"])
    ws1.append(["1月", 100])
    ws1.append(["2月", 200])
    ws2 = workbook.create_sheet("库存")
    ws2.append(["商品", "数量"])
    ws2.append(["A", 5])
    ws2.append([None, None])  # 全空行，应被跳过
    ws2.append(["B", 7])
    buf = io.BytesIO()
    workbook.save(buf)

    parsed = parse_document("数据表.xlsx", buf.getvalue())
    tables = [b for b in parsed.blocks if b.type == "table"]
    assert len(tables) == 2
    assert tables[0].text == "销售"  # block.text 存 sheet 名
    assert tables[0].rows == [["月份", "金额"], ["1月", "100"], ["2月", "200"]]
    assert tables[1].text == "库存"
    assert tables[1].rows == [["商品", "数量"], ["A", "5"], ["B", "7"]]
    assert parsed.title == "数据表"


# ---------------------------------------------------------------- pdf

def test_pdf_roundtrip_text_and_page_numbers():
    document = pymupdf.open()
    page1 = document.new_page()
    page1.insert_text((72, 72), "EvoCode RAG parse test.", fontsize=14)
    page2 = document.new_page()
    page2.insert_text((72, 72), "Second page content here.", fontsize=12)
    data = document.tobytes()
    document.close()

    parsed = parse_document("sample.pdf", data)
    assert parsed.title == "sample"
    assert len(parsed.blocks) == 2
    assert parsed.blocks[0].page == 1
    assert "EvoCode RAG parse test" in parsed.blocks[0].text
    assert parsed.blocks[1].page == 2
    assert "Second page content" in parsed.blocks[1].text


def test_encrypted_pdf_recorded_in_warnings_and_empty_text():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Top secret.", fontsize=12)
    data = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user"
    )
    document.close()

    parsed = parse_document("secret.pdf", data)
    assert parsed.warnings, "加密 PDF 必须写入 warnings"
    assert parsed.text == ""
    assert parsed.blocks == []


# ---------------------------------------------------------------- 异常路径

def test_unsupported_extension_raises_value_error():
    with pytest.raises(ValueError, match="不支持的文件格式"):
        parse_document("archive.exe", b"MZ whatever")


@pytest.mark.parametrize(
    "filename,data",
    [
        ("broken.pdf", b"not-a-pdf"),
        ("broken.docx", b"this is not a zip container"),
        ("broken.xlsx", b"\x00\x01\x02 garbage"),
    ],
)
def test_corrupted_bytes_raise_value_error_with_original_info(filename, data):
    with pytest.raises(ValueError, match="解析失败") as exc_info:
        parse_document(filename, data)
    # 附原始异常信息（__cause__ 链或消息内含原始异常）
    assert exc_info.value.__cause__ is not None or str(exc_info.value) != "解析失败"


# ---------------------------------------------------------------- chunker

def _build_long_md(total_chars: int = 6000) -> bytes:
    sentence = "EvoCode解析器需要对超长段落做滑窗切分，保证相邻chunk内容连续。"
    body = sentence * (total_chars // len(sentence) + 1)
    return f"# 长文档\n{body}\n".encode("utf-8")


def test_chunker_long_doc_nonempty_unique_ids_and_adjacent_overlap():
    parsed = parse_document("long.md", _build_long_md())
    chunks = chunk_document(parsed, max_chars=800, overlap=100)
    assert chunks, "长文档必须切出非空 chunk"
    assert all(c.text.strip() for c in chunks)
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)), "chunk.id 必须唯一"
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # 相邻 chunk 内容连续：第 n 个的尾部是第 n+1 个头部的子串
    overlaps_found = 0
    for prev, nxt in zip(chunks, chunks[1:]):
        tail = prev.text[-40:]
        if tail and tail in nxt.text:
            overlaps_found += 1
    assert overlaps_found >= max(1, len(chunks) - 1), (
        "同 section 内相邻 chunk 必须存在重叠内容"
    )
    # chunk 数量处于合理区间：不低于 ceil(总文本量/max_chars)
    total = len(parsed.text)
    assert len(chunks) >= math.ceil(total / 800)
    assert all(c.doc_id == "long" for c in chunks)
    assert all(c.meta["doc_title"] == parsed.title for c in chunks)


def test_chunker_respects_heading_boundaries_and_meta():
    md = (
        "# 概述\n"
        "概述段落，篇幅适中。\n"
        "\n"
        "# 安装\n"
        "安装步骤段落。\n"
        "\n"
        "## 配置\n"
        "配置说明段落。\n"
    ).encode("utf-8")
    parsed = parse_document("guide.md", md)
    chunks = chunk_document(parsed, max_chars=800, overlap=100)
    assert len(chunks) >= 3  # 三个 section，各至少一个 chunk
    for chunk in chunks:
        assert chunk.text.strip()
        assert chunk.source.startswith("guide.md § ")
        assert chunk.meta["page"] is None
        assert chunk.meta["doc_title"] == "概述"
    # chunk 不跨 heading：没有 chunk 同时包含两个不同 section 的标题
    for chunk in chunks:
        assert not (("概述" in chunk.text) and ("安装" in chunk.text and "配置" in chunk.text)), (
            "chunk 不得跨 heading 边界"
        )
    section_titles = [c.meta["section"] for c in chunks]
    assert section_titles == ["概述", "安装", "配置"]
    assert all(c.id.startswith("guide:") for c in chunks)


def test_chunker_pdf_chunks_carry_page_and_source():
    document = pymupdf.open()
    for i in range(2):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {i + 1} body text.", fontsize=12)
    data = document.tobytes()
    document.close()

    parsed = parse_document("book.pdf", data)
    chunks = chunk_document(parsed, max_chars=800, overlap=100)
    assert len(chunks) == 2
    assert [c.meta["page"] for c in chunks] == [1, 2]
    assert chunks[0].source == "book.pdf § 第1页"
    assert "Page 1 body text." in chunks[0].text


def test_chunker_table_serialized_and_xlsx_source_hints_sheet_name():
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "汇总"
    ws.append(["指标", "数值"])
    ws.append(["营收", "100"])
    buf = io.BytesIO()
    workbook.save(buf)

    parsed = parse_document("table.xlsx", buf.getvalue())
    chunks = chunk_document(parsed, max_chars=800, overlap=100)
    assert len(chunks) == 1
    assert chunks[0].text == "汇总\n\n指标 | 数值\n营收 | 100"
    assert chunks[0].meta["section"] == "汇总"
    assert chunks[0].source == "table.xlsx § 汇总"


def test_chunker_empty_md_and_txt_return_no_chunks():
    for name, raw in (("empty.md", b""), ("empty.txt", b"   \n\n  \n")):
        parsed = parse_document(name, raw)
        assert isinstance(parsed, ParsedDocument)
        assert chunk_document(parsed) == []

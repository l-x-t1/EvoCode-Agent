"""B6 RAG 统一文档解析器：md/txt/html/pdf/docx/xlsx → ParsedDocument。

契约见 types.py：DocBlock.type ∈ heading | paragraph | table | page；
解析失败（损坏文件等）抛 ValueError(f"解析失败: {filename} ...")，
不支持的后缀抛 UnsupportedFormatError（ValueError 子类）。
"""

from __future__ import annotations

import io
import os
import re
from html.parser import HTMLParser

from .types import DocBlock, ParsedDocument

__all__ = ["UnsupportedFormatError", "parse_document"]

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_DOCX_HEADING_RE = re.compile(r"^Heading\s+([1-6])$", re.IGNORECASE)
_HTML_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


class UnsupportedFormatError(ValueError):
    """不支持的后缀。"""


def _stem(filename: str) -> str:
    return os.path.splitext(os.path.basename(filename))[0]


# --------------------------------------------------------------------------- md

def _parse_md(filename: str, data: bytes) -> ParsedDocument:
    text = data.decode("utf-8", errors="replace")
    blocks: list[DocBlock] = []
    title: str | None = None
    para: list[str] = []
    in_code = False
    code: list[str] = []

    def flush_para() -> None:
        if para:
            joined = "\n".join(para).strip()
            if joined:
                blocks.append(DocBlock("paragraph", joined))
            para.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if in_code:
            if stripped.startswith("```"):
                joined = "\n".join(code).strip()
                if joined:
                    blocks.append(DocBlock("paragraph", joined))
                code = []
                in_code = False
            else:
                code.append(line)
            continue
        if stripped.startswith("```"):
            flush_para()
            in_code = True
            code = []
            continue
        m = _MD_HEADING_RE.match(stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            if title is None and heading_text:
                title = heading_text  # 文档内首个 heading 作为更好的标题
            blocks.append(DocBlock("heading", heading_text, level=level))
            continue
        if not stripped:
            flush_para()
            continue
        para.append(line)
    # 未闭合的代码块：剩余内容整体作为 paragraph，不报错
    if in_code and code:
        joined = "\n".join(code).strip()
        if joined:
            blocks.append(DocBlock("paragraph", joined))
    flush_para()
    return ParsedDocument(filename=filename, title=title or _stem(filename), blocks=blocks)


# --------------------------------------------------------------------------- txt

def _parse_txt(filename: str, data: bytes) -> ParsedDocument:
    text = data.decode("utf-8", errors="replace")
    blocks: list[DocBlock] = []
    for seg in re.split(r"\n\s*\n", text):
        body = "\n".join(line.rstrip() for line in seg.splitlines()).strip()
        if body:
            blocks.append(DocBlock("paragraph", body))
    return ParsedDocument(filename=filename, title=_stem(filename), blocks=blocks)


# --------------------------------------------------------------------------- html

class _HTMLExtractor(HTMLParser):
    """提取 title / h1~h6 / p / table；script 与 style 内容丢弃。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doc_title: str | None = None
        self.blocks: list[DocBlock] = []
        self._skip = 0                 # script/style 嵌套深度
        self._mode: tuple[str, int] | None = None   # ("title"|"p"|"h", level)
        self._buf: list[str] = []
        self._rows: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    # -- helpers ------------------------------------------------------------
    def _flush_open_block(self) -> None:
        if self._mode and self._mode[0] in ("p", "h"):
            body = " ".join("".join(self._buf).split())
            if body:
                if self._mode[0] == "h":
                    self.blocks.append(DocBlock("heading", body, level=self._mode[1]))
                else:
                    self.blocks.append(DocBlock("paragraph", body))
        elif self._mode and self._mode[0] == "title":
            body = " ".join("".join(self._buf).split())
            if body and self.doc_title is None:
                self.doc_title = body
        self._mode = None
        self._buf = []

    def _flush_open_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    # -- parser hooks ---------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        if t == "title":
            self._flush_open_block()
            self._mode = ("title", 0)
            self._buf = []
        elif t in _HTML_HEADINGS:
            self._flush_open_block()
            self._mode = ("h", _HTML_HEADINGS[t])
            self._buf = []
        elif t == "p":
            self._flush_open_block()
            self._mode = ("p", 0)
            self._buf = []
        elif t == "table":
            self._flush_open_block()
            self._rows = []
        elif t == "tr" and self._rows is not None:
            self._flush_open_cell()
            self._row = []
        elif t in ("td", "th") and self._row is not None:
            self._flush_open_cell()
            self._cell = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if t == "title" and self._mode and self._mode[0] == "title":
            self._flush_open_block()
        elif t in _HTML_HEADINGS and self._mode and self._mode[0] == "h":
            self._flush_open_block()
        elif t == "p" and self._mode and self._mode[0] == "p":
            self._flush_open_block()
        elif t == "table" and self._rows is not None:
            self._flush_open_cell()
            if self._row:
                self._rows.append(self._row)
                self._row = None
            if self._rows:
                self.blocks.append(DocBlock("table", "", rows=self._rows))
            self._rows = None
        elif t == "tr" and self._row is not None and self._rows is not None:
            self._flush_open_cell()
            self._rows.append(self._row)
            self._row = None
        elif t in ("td", "th") and self._cell is not None:
            self._flush_open_cell()

    def handle_data(self, data):
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._mode is not None:
            self._buf.append(data)

    def handle_entityref(self, name):  # convert_charrefs=True 时不会触发，保险起见
        self.handle_data(f"&{name};")


def _parse_html(filename: str, data: bytes) -> ParsedDocument:
    text = data.decode("utf-8", errors="replace")
    parser = _HTMLExtractor()
    parser.feed(text)
    parser.close()
    return ParsedDocument(
        filename=filename,
        title=parser.doc_title or _stem(filename),
        blocks=parser.blocks,
    )


# --------------------------------------------------------------------------- pdf

def _parse_pdf(filename: str, data: bytes) -> ParsedDocument:
    import pymupdf  # 延迟导入；避免 `import fitz` 的 FutureWarning

    blocks: list[DocBlock] = []
    extra_warnings: list[str] = []
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                if not doc.authenticate(""):
                    extra_warnings.append(f"{filename}: PDF 已加密，无法提取文本（text 为空）")
                    return ParsedDocument(
                        filename=filename,
                        title=_stem(filename),
                        blocks=[],
                        warnings=extra_warnings,
                    )
            if doc.page_count == 0:
                raise ValueError("空或损坏的 PDF（0 页）")
            for i in range(doc.page_count):
                page_text = doc[i].get_text("text").strip()
                if page_text:
                    blocks.append(DocBlock("paragraph", page_text, page=i + 1))
    except ValueError:
        raise
    except Exception as exc:  # 损坏 bytes 等
        raise ValueError(f"解析失败: {filename}（{type(exc).__name__}: {exc}）") from exc
    return ParsedDocument(
        filename=filename,
        title=_stem(filename),
        blocks=blocks,
        warnings=extra_warnings,
    )


# --------------------------------------------------------------------------- docx

def _parse_docx(filename: str, data: bytes) -> ParsedDocument:
    import docx as docx_lib
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx_lib.Document(io.BytesIO(data))
    blocks: list[DocBlock] = []
    # 按 body 实际顺序遍历段落与表格，保持「标题→段落→表格」的文档顺序
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, document)
            body = p.text.strip()
            if not body:
                continue
            style_name = ""
            try:
                style_name = p.style.name or "" if p.style is not None else ""
            except Exception:
                style_name = ""
            m = _DOCX_HEADING_RE.match(style_name)
            if m:
                blocks.append(DocBlock("heading", body, level=int(m.group(1))))
            else:
                blocks.append(DocBlock("paragraph", body))
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            rows = [r for r in rows if any(c for c in r)]
            if rows:
                blocks.append(DocBlock("table", "", rows=rows))
    return ParsedDocument(filename=filename, title=_stem(filename), blocks=blocks)


# --------------------------------------------------------------------------- xlsx

def _parse_xlsx(filename: str, data: bytes) -> ParsedDocument:
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    blocks: list[DocBlock] = []
    try:
        for sheet in workbook.worksheets:
            rows: list[list[str]] = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                if any(c.strip() for c in cells):  # 跳过全空行
                    rows.append(cells)
            # block.text 存 sheet 名，作为来源提示；数据放 rows
            blocks.append(DocBlock("table", sheet.title or "", rows=rows))
    finally:
        workbook.close()
    return ParsedDocument(filename=filename, title=_stem(filename), blocks=blocks)


# --------------------------------------------------------------------------- 入口

_HANDLERS = {
    "md": _parse_md,
    "markdown": _parse_md,
    "txt": _parse_txt,
    "html": _parse_html,
    "htm": _parse_html,
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "xlsx": _parse_xlsx,
}


def parse_document(filename: str, data: bytes) -> ParsedDocument:
    """按扩展名（不区分大小写）分派解析；title 默认文件名去扩展名。

    不支持的后缀 → UnsupportedFormatError（ValueError 子类）；
    解析失败（损坏文件等）→ ValueError(f"解析失败: {filename} ...")，附原始异常信息。
    """
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    handler = _HANDLERS.get(ext)
    if handler is None:
        raise UnsupportedFormatError(f"不支持的文件格式: .{ext}（文件: {filename}）")
    try:
        return handler(filename, data)
    except UnsupportedFormatError:
        raise
    except ValueError as exc:
        if str(exc).startswith("解析失败:"):
            raise
        raise ValueError(f"解析失败: {filename}（ValueError: {exc}）") from exc
    except Exception as exc:
        raise ValueError(f"解析失败: {filename}（{type(exc).__name__}: {exc}）") from exc

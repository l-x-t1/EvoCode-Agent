"""B6 RAG 分块器：ParsedDocument → list[Chunk]。

规则：
- doc_id = 文件名去扩展名；chunk.id = f"{doc_id}:{index}"
- 以 heading 为界分 section（chunk 不跨 heading）；单个段落/表格超长时
  按句子切分并保留 overlap 字符重叠，保证相邻 chunk 内容连续
- table 序列化为「表头行 | 数据行」文本参与切分
- source = f"{filename} § {最近 heading 或 第n页}"；meta 存 section/page/doc_title
"""

from __future__ import annotations

import os
import re

from .types import Chunk, DocBlock, ParsedDocument

__all__ = ["chunk_document"]

# 句子边界：中文句末标点 / 英文句读 / 换行；标点跟随前句
_SENT_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;\n]*")


def _table_to_text(rows: list[list[str]]) -> str:
    """表格 → 文本：每行单元格用 " | " 连接，行间换行；首行为表头。"""
    if not rows:
        return ""
    return "\n".join(" | ".join(cell for cell in row) for row in rows)


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    """超长文本按句子切成 ≤ max_chars 的片段；相邻片段共享 overlap 字符尾部。"""
    if len(text) <= max_chars:
        return [text]
    sentences = [s for s in _SENT_RE.findall(text) if s.strip()]
    pieces: list[str] = []
    cur = ""
    for s in sentences:
        if len(s) > max_chars:
            # 单句超过窗口：退化为字符窗口滑动（带 overlap）
            if cur.strip():
                pieces.append(cur)
                cur = ""
            step = max(1, max_chars - overlap)
            start = 0
            while start < len(s):
                pieces.append(s[start:start + max_chars])
                if start + max_chars >= len(s):
                    break
                start += step
            continue
        if cur and len(cur) + len(s) > max_chars:
            pieces.append(cur)
            tail = cur[-overlap:] if overlap > 0 else ""
            room = max_chars - len(s)
            if len(tail) > room:
                tail = tail[-room:] if room > 0 else ""
            cur = tail  # 下一片段以前一片段尾部开头 → 相邻 chunk 重叠
        cur += s
    if cur.strip():
        pieces.append(cur)
    return [p for p in pieces if p.strip()]


def _build_sections(parsed: ParsedDocument) -> list[dict]:
    """按 heading 边界把 blocks 切成 section；无 heading 时按 page（PDF）分组。"""
    sections: list[dict] = []
    cur: dict | None = None

    def flush() -> None:
        nonlocal cur
        if cur is not None and (cur["texts"] or cur["title"]):
            sections.append(cur)
        cur = None

    for block in parsed.blocks:
        if block.type == "heading":
            flush()
            title = block.text.strip()
            cur = {"title": title or None, "page": None, "texts": []}
            if title:
                cur["texts"].append(title)  # 标题文本本身参与 chunk，便于检索定位
        elif block.type == "table":
            serialized = _table_to_text(block.rows)
            label = (block.text or "").strip() or None  # xlsx sheet 名提示
            if cur is None:
                cur = {"title": None, "page": block.page, "texts": []}
            elif cur["title"] is None and block.page is not None and cur["page"] != block.page:
                flush()
                cur = {"title": None, "page": block.page, "texts": []}
            if cur["title"] is None and label:
                cur["title"] = label
                cur["texts"].append(label)  # sheet 名等来源提示进入文本
            if serialized:
                cur["texts"].append(serialized)
            elif label:
                cur["texts"].append(label)
        elif block.type in ("paragraph", "page"):
            body = (block.text or "").strip()
            if not body:
                continue
            if cur is None:
                cur = {"title": None, "page": block.page, "texts": []}
            elif cur["title"] is None and block.page is not None and cur["page"] != block.page:
                flush()  # PDF：无标题时按页分组
                cur = {"title": None, "page": block.page, "texts": []}
            cur["texts"].append(body)
    flush()
    return sections


def _chunk_section(texts: list[str], max_chars: int, overlap: int) -> list[str]:
    """一个 section 内部：先对超长元素滑窗切分，再贪心合并小片段到 max_chars。"""
    if not texts:
        return []
    total = sum(len(t) for t in texts) + 2 * (len(texts) - 1)
    if total <= max_chars:
        return ["\n\n".join(texts)]
    pieces: list[str] = []
    for t in texts:
        if len(t) > max_chars:
            pieces.extend(_split_long(t, max_chars, overlap))
        else:
            pieces.append(t)
    out: list[str] = []
    buf = ""
    for piece in pieces:
        if not buf:
            buf = piece
        elif len(buf) + 2 + len(piece) <= max_chars:
            buf += "\n\n" + piece
        else:
            out.append(buf)
            buf = piece
    if buf:
        out.append(buf)
    return out


def chunk_document(
    parsed: ParsedDocument, *, max_chars: int = 800, overlap: int = 100
) -> list[Chunk]:
    """把解析产物切成 Chunk 列表；空文档返回 []。

    chunk 总数保持在 ceil(总文本量/max_chars) 到按最小段切分之间：不足 max_chars
    的相邻片段会被合并，超长片段才滑窗切分并带 overlap。
    """
    if max_chars <= 0:
        raise ValueError("max_chars 必须为正数")
    overlap = max(0, min(overlap, max_chars - 1))
    doc_id = os.path.splitext(os.path.basename(parsed.filename))[0]
    chunks: list[Chunk] = []
    index = 0
    for section in _build_sections(parsed):
        for text in _chunk_section(section["texts"], max_chars, overlap):
            text = text.strip()
            if not text:
                continue
            label = section["title"] or (
                f"第{section['page']}页" if section["page"] else None
            )
            source = f"{parsed.filename} § {label}" if label else parsed.filename
            chunks.append(
                Chunk(
                    id=f"{doc_id}:{index}",
                    doc_id=doc_id,
                    doc_title=parsed.title,
                    index=index,
                    text=text,
                    source=source,
                    meta={
                        "section": section["title"],
                        "page": section["page"],
                        "doc_title": parsed.title,
                    },
                )
            )
            index += 1
    return chunks

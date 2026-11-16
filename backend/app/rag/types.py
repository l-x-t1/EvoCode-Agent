"""RAG 数据契约（B6）：解析产物与 chunk 的统一形状。

parsers.py / chunker.py / service.py 共同遵守；字段语义：
- DocBlock.type: heading | paragraph | table | page
- heading 级别 level 1~6；table.rows 为行数组（首行视为表头）
- Chunk.meta.source 记录来源（文件名 + 标题/页码），引用来源追踪的数据基础
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DocBlock:
    type: str                       # heading | paragraph | table | page
    text: str = ""
    level: int | None = None        # heading 层级
    rows: list[list[str]] = field(default_factory=list)  # table 行
    page: int | None = None         # PDF 页码等来源定位


@dataclass
class ParsedDocument:
    filename: str
    title: str
    blocks: list[DocBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # 解析异常/质量提示（如实记录）

    @property
    def text(self) -> str:
        return "\n".join(b.text or "" for b in self.blocks if b.text)


@dataclass
class Chunk:
    id: str                          # {doc_id}:{index}
    doc_id: str
    doc_title: str
    index: int
    text: str
    source: str                      # 引用定位：文件名 § 标题/页码
    meta: dict = field(default_factory=dict)

"""BM25 检索（B6）：纯 Python 实现 OKAPI BM25，无外部依赖。

- 索引在内存中随语料重建（load 后 build；语料变更由 RagService 触发 rebuild）
- 中文分词：MVP 用字符 2-gram（与 Hashing 嵌入口径一致）；ASCII 词按空格/标点切
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in re.split(r"[\s\d\W_]+", text.lower()) if re.search(r"[A-Za-z]", text) else []:
        if word:
            tokens.append(word)
    # 中文按 2-gram
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    for run in cjk_runs:
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


@dataclass
class BM25Index:
    """OKAPI BM25：k1=1.5, b=0.75（经典参数）。"""

    k1: float = 1.5
    b: float = 0.75
    _docs: dict[str, Counter] = field(default_factory=dict)   # chunk_id -> term freq
    _doc_len: dict[str, int] = field(default_factory=dict)
    _df: Counter = field(default_factory=Counter)             # 词 -> 含该词文档数
    _avg_len: float = 0.0

    def build(self, corpus: dict[str, str]) -> None:
        """corpus: chunk_id -> text。全量重建（MVP 语料规模 ≤ 数千 chunk）。"""
        self._docs.clear()
        self._doc_len.clear()
        self._df.clear()
        for cid, text in corpus.items():
            tokens = _tokenize(text)
            tf = Counter(tokens)
            self._docs[cid] = tf
            self._doc_len[cid] = len(tokens)
            for term in tf:
                self._df[term] += 1
        self._avg_len = (sum(self._doc_len.values()) / len(self._doc_len)) if self._doc_len else 0.0

    def __len__(self) -> int:
        return len(self._docs)

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if not self._docs:
            return []
        q_tokens = _tokenize(query)
        scores: dict[str, float] = {}
        n = len(self._docs)
        for cid, tf in self._docs.items():
            dl = self._doc_len[cid]
            score = 0.0
            for term in q_tokens:
                f = tf.get(term, 0)
                if f == 0:
                    continue
                idf = math.log((n - self._df[term] + 0.5) / (self._df[term] + 0.5) + 1.0)
                score += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / (self._avg_len or 1)))
            if score > 0:
                scores[cid] = score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

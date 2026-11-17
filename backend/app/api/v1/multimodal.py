"""多模态路由（B7）：OCR / 图片理解 / 图表问答 三个分立端点 + OCR→RAG 关联。

JSON 入参：{filename, dataBase64, mime}（前端上传入口随 B8）；
图片与文档关联：OCR 结果可作为文档导入 RAG 语料（ocrAndIndex）。
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.multimodal.vision import MultimodalInput, get_vision_client
from app.rag.service import get_rag_service

router = APIRouter(prefix="/multimodal", tags=["multimodal"])


class ImageIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    dataBase64: str = Field(min_length=1)
    mime: str = Field(min_length=1, max_length=64)


class ChartQaIn(ImageIn):
    question: str = Field(min_length=1, max_length=1000)


class OcrAndIndexIn(ImageIn):
    docId: str | None = Field(default=None, description="关联的 RAG 文档 id（缺省用文件名）")


def _to_input(body: ImageIn) -> MultimodalInput:
    try:
        data = base64.b64decode(body.dataBase64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BizException(ErrorCode.VALIDATION_ERROR, "dataBase64 不是合法 Base64",
                           status_code=422) from exc
    return MultimodalInput(filename=body.filename, data=data, mime=body.mime)


@router.post("/ocr")
async def ocr_image(body: ImageIn, _: AsyncSession = Depends(get_db)) -> dict:
    """能力一：OCR。图片 → 文本（含区域定位与页码来源）。"""
    result = await get_vision_client().ocr(_to_input(body))
    return {"text": result.text, "regions": result.regions,
            "language": result.language, "filename": body.filename}


@router.post("/understand")
async def understand_image(body: ImageIn, _: AsyncSession = Depends(get_db)) -> dict:
    """能力二：图片理解。结构化描述（对象/场景/图内文字）。"""
    result = await get_vision_client().understand(_to_input(body))
    return {"description": result.description, "objects": result.objects,
            "scene": result.scene, "textFound": result.text_found, "filename": body.filename}


@router.post("/chart-qa")
async def chart_qa(body: ChartQaIn, _: AsyncSession = Depends(get_db)) -> dict:
    """能力三：图表问答。图表图片 + 问题 → 数据级回答（含读出数值）。"""
    result = await get_vision_client().chart_qa(_to_input(body), body.question)
    return {"answer": result.answer, "values": result.values,
            "chartType": result.chart_type, "filename": body.filename}


@router.post("/ocr-and-index")
async def ocr_and_index(body: OcrAndIndexIn, _: AsyncSession = Depends(get_db)) -> dict:
    """OCR + 图片与文档关联：识别文字导入 RAG 语料（docId 缺省用图片文件名）。"""
    result = await get_vision_client().ocr(_to_input(body))
    if not result.text.strip():
        raise BizException(ErrorCode.INVALID_REQUEST, "OCR 未提取到文字，无法建立索引",
                           status_code=422)
    rag = get_rag_service()
    doc_id = body.docId or body.filename.rsplit(".", 1)[0]
    content = f"# {body.filename}（OCR）\n\n" + result.text
    import_result = await rag.import_document(f"{doc_id}.ocr.md", content.encode("utf-8"))
    return {"ocr": {"text": result.text, "regions": result.regions,
                    "language": result.language},
            "indexed": {"docId": import_result.doc_id, "chunkCount": import_result.chunk_count}}

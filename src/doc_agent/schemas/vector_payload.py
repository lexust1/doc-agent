from pydantic import BaseModel, Field
from typing import List, Optional, Dict


class PayloadMetadata(BaseModel):
    """Metadata attached to each text chunk for precise filtering and source citation in Qdrant."""

    doc_id: str = Field(
        description="The unique identifier of the parent document (e.g., 'gost_10704')."
    )
    source_pdf: str = Field(
        description="Path or filename of the original source PDF for user download/comparison."
    )
    pages: List[str] = Field(
        description="List of physical page IDs this chunk spans across (e.g., ['page_0001', 'page_0002'])."
    )
    page_artifacts: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of page IDs to their processed artifact paths (e.g., {'page_0001': '02_rendered/page_0001.png'})."
    )
    h1: Optional[str] = Field(
        default=None,
        description="The highest-level section title or header from the document structure."
    )
    h2: Optional[str] = Field(
        default=None,
        description="The secondary section title or chapter header."
    )
    h3: Optional[str] = Field(
        default=None,
        description="The tertiary section title or topic header."
    )
    h4: Optional[str] = Field(
        default=None,
        description="The quaternary section title or precise clause identifier (e.g., '1.7.1')."
    )


class VectorPayload(BaseModel):
    """Data contract representing a single text chunk and its metadata, ready for Qdrant storage."""

    chunk_id: str = Field(
        description="A unique identifier or cryptographic hash computed for this specific chunk."
    )
    text: str = Field(
        description="The actual text content to be embedded and indexed for search."
    )
    metadata: PayloadMetadata = Field(
        description="The structural and physical metadata container for database filtering."
    )
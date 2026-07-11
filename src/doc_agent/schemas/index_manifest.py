from pydantic import BaseModel, Field


class IndexManifest(BaseModel):
    """Tracks whether a document has been fully indexed into Qdrant."""

    doc_id: str = Field(
        description="Document identifier."
        )
    indexed: bool = Field(
        default=False, 
        description="True if all chunks are upserted."
        )
    indexed_at: str | None = Field(
        default=None, 
        description="ISO timestamp of indexing."
        )
    chunk_count: int = Field(
        default=0, 
        description="Number of chunks indexed."
        )
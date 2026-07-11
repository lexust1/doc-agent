from pydantic import BaseModel, Field
from typing import List


class PageContent(BaseModel):
    """Represents the extracted content and metadata of a single processed page."""
    
    page_id: str = Field(
        description="Unique identifier for the page (e.g., 'page_0001')."
    )
    markdown: str = Field(
        description="Cleaned, semantically normalized Markdown text for this page."
    )


class AggregatedDocument(BaseModel):
    """
    Data contract for the fully aggregated document.
    
    Acts as the bridge between isolated page processing and the semantic chunker.
    It holds both the discrete page structures and the continuous text stream 
    with embedded physical page anchors.
    """
    
    doc_id: str = Field(
        description="Unique identifier for the aggregated document (e.g., 'gost_10704')."
    )
    total_pages: int = Field(
        description="Total number of successfully processed and aggregated pages."
    )
    pages: List[PageContent] = Field(
        default_factory=list, 
        description="List of discrete page contents ordered by physical appearance."
    )
    full_text: str = Field(
        description="Concatenated markdown text with invisible HTML anchors (<!-- page_XXXX -->)."
    )
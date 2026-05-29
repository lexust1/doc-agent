from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class GlobalStatus(str, Enum):
    """Represents the overall processing status of the document."""
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PageStatus(str, Enum):
    """Represents the processing stage of an individual page."""
    PENDING = "pending"
    RENDERED = "rendered"
    TAGGED = "tagged"
    CLEANED = "cleaned"
    FAILED = "failed"


class PageState(BaseModel):
    """Pydantic model representing the state and artifacts of a single page."""
    
    status: PageStatus = Field(
        default=PageStatus.PENDING,
        description="Current processing stage of the page."
    )
    complexity_flags: List[str] = Field(
        default_factory=list,
        description="Flags indicating complex elements (e.g., 'dense_table', 'rotated')."
    )
    paths: Dict[str, str] = Field(
        default_factory=dict,
        description="Relative storage paths to page artifacts (e.g., 'pdf', 'clean_md')."
    )
    figures: List[str] = Field(
        default_factory=list,
        description="List of relative paths to extracted figure images."
    )


class DocumentManifest(BaseModel):
    """Pydantic model representing the document's complete lifecycle manifest."""
    
    doc_id: str = Field(
        description="Unique identifier for the document."
    )
    source_file: Path = Field(
        description="Path to the original source PDF."
    )
    total_pages: int = Field(
        description="Total number of pages in the document."
    )
    global_status: GlobalStatus = Field(
        default=GlobalStatus.PROCESSING,
        description="Overall processing status of the document."
    )
    pages: Dict[str, PageState] = Field(
        default_factory=dict,
        description="Dictionary mapping page IDs to their processing states."
    )
    aggregated_file: Optional[str] = Field(
        default=None, 
        description="Relative path to the final aggregated JSON document."
    )
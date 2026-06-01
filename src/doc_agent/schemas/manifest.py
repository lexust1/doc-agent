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
    """Pydantic model representing the state and artifacts of a single page.

    Example:
    
    A freshly initialised page:

        PageState(status=<PageStatus.PENDING: 'pending'>, complexity_flags=[], paths={}, figures=[])

    A page that has been tagged and contains a figure::

        PageState(
            status=<PageStatus.TAGGED: 'tagged'>,
            complexity_flags=['dense_table'],
            paths={'tagged_md': '03_md_tagged/page_0001.md'},
            figures=['figures/page_0001_image_1.png']
        )
    """
    
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
    """Pydantic model representing the document's complete lifecycle manifest.

    Example:

    A manifest for a two‑page document after the pipeline has processed
    the first page (tagged) and the second page (fully cleaned), with
    aggregation complete:

        DocumentManifest(
            doc_id='pue_1_3',
            source_file=Path('data/01_raw/pue_1_3.pdf'),
            total_pages=2,
            global_status=<GlobalStatus.COMPLETED: 'completed'>,
            pages={
                'page_0001': PageState(
                    status=<PageStatus.TAGGED: 'tagged'>,
                    complexity_flags=['ghost_table'],
                    paths={
                        'pdf': '01_pages_pdf/page_0001.pdf',
                        'png': '02_renders_png/page_0001_highres.png',
                        'tagged_md': '03_md_tagged/page_0001.md'
                    },
                    figures=['figures/page_0001_image_1.png']
                ),
                'page_0002': PageState(
                    status=<PageStatus.CLEANED: 'cleaned'>,
                    complexity_flags=[],
                    paths={
                        'pdf': '01_pages_pdf/page_0002.pdf',
                        'png': '02_renders_png/page_0002_highres.png',
                        'tagged_md': '03_md_tagged/page_0002.md',
                        'clean_md': '04_md_clean/page_0002.md'
                    },
                    figures=[]
                )
            },
            aggregated_file='05_aggregated/pue_1_3.json'
        )
    """
    
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
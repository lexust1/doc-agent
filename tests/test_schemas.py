import json
from pathlib import Path
import pytest
from doc_agent.schemas.manifest import (
    GlobalStatus,
    PageStatus,
    PageState,
    DocumentManifest
)

# ------------------------------------------------------------------
# 1. Enums
# ------------------------------------------------------------------
def test_global_status_members():
    """Ensure the GlobalStatus enum contains exactly the expected states."""
    members = {s.value for s in GlobalStatus}
    assert members == {"processing", "completed", "failed"}

def test_page_status_members():
    """Ensure the PageStatus enum contains all five pipeline states."""
    members = {s.value for s in PageStatus}
    assert members == {"pending", "rendered", "tagged", "cleaned", "failed"}


# ------------------------------------------------------------------
# 2. PageState – construction and field types
# ------------------------------------------------------------------
def test_page_state_default():
    """Verify that a newly created PageState has the correct defaults:
    status PENDING, no complexity flags, no artifact paths, and no figures.
    """
    state = PageState()
    assert state.status == PageStatus.PENDING
    assert state.complexity_flags == []
    assert state.paths == {}
    assert state.figures == []
    
def test_page_state_explicit_values():
    """You can create a PageState with a specific status and artifacts."""
    state = PageState(
        status=PageStatus.TAGGED,
        complexity_flags=["dense_table"],
        paths={"tagged_md": "03_md_tagged/page_0001.md"},
        figures=["figures/page_0001_image_1.png"],
    )
    assert state.status == PageStatus.TAGGED
    assert state.complexity_flags == ["dense_table"]
    assert state.paths == {"tagged_md": "03_md_tagged/page_0001.md"}
    assert state.figures == ["figures/page_0001_image_1.png"]

def test_page_status_must_be_enum():
    """Pydantic should reject a string that's not a valid PageStatus."""
    with pytest.raises(ValueError):  
        PageState(status="invalid_status")


# ------------------------------------------------------------------
# 3. DocumentManifest – creation and nested PageState
# ------------------------------------------------------------------
def test_document_manifest_creation():
    """Create a minimal manifest with two pages and check fields."""
    manifest = DocumentManifest(
        doc_id="test_doc",
        source_file=Path("/fake/source.pdf"),
        total_pages=2,
        pages={
            "page_0001": PageState(),
            "page_0002": PageState(status=PageStatus.CLEANED),
        },
    )
    assert manifest.doc_id == "test_doc"
    assert manifest.source_file == Path("/fake/source.pdf")
    assert manifest.total_pages == 2
    assert manifest.global_status == GlobalStatus.PROCESSING
    assert len(manifest.pages) == 2
    assert manifest.pages["page_0001"].status == PageStatus.PENDING
    assert manifest.pages["page_0002"].status == PageStatus.CLEANED

def test_document_manifest_default_status():
    """The global_status should default to PROCESSING."""
    manifest = DocumentManifest(
        doc_id="d", source_file=Path("x.pdf"), total_pages=0
    )
    assert manifest.global_status == GlobalStatus.PROCESSING

def test_document_manifest_optional_aggregated_file():
    """aggregated_file defaults to None, but can be explicitly set."""
    # Case 1: Not provided → should be None
    manifest_default = DocumentManifest(
        doc_id="d", source_file=Path("x.pdf"), total_pages=0,
    )
    assert manifest_default.aggregated_file is None

    # Case 2: Provided → should store the value
    manifest_set = DocumentManifest(
        doc_id="d", source_file=Path("x.pdf"), total_pages=0,
        aggregated_file="05_aggregated/d.json",
    )
    assert manifest_set.aggregated_file == "05_aggregated/d.json"


# ------------------------------------------------------------------
# 4. Serialization round‑trip (JSON)
# ------------------------------------------------------------------
def test_document_manifest_json_roundtrip():
    """After dumping to JSON and reloading, all data is preserved."""
    manifest = DocumentManifest(
        doc_id="gost_10704",
        source_file=Path("/data/gost_10704.pdf"),
        total_pages=2,
        pages={
            "page_0001": PageState(
                status=PageStatus.TAGGED,
                complexity_flags=["ghost_table"],
                paths={"pdf": "01_pages_pdf/page_0001.pdf"},
                figures=["figures/image_1.png"],
            ),
            "page_0002": PageState(status=PageStatus.CLEANED),
        },
        global_status=GlobalStatus.PROCESSING,
    )

    # Serialize to JSON string
    json_str = manifest.model_dump_json(indent=2)
    # Parse back into a dict and recreate the model
    loaded = DocumentManifest(**json.loads(json_str))

    assert loaded.doc_id == manifest.doc_id
    assert loaded.source_file == manifest.source_file
    assert loaded.total_pages == manifest.total_pages
    assert loaded.global_status == manifest.global_status
    assert loaded.pages["page_0001"].status == PageStatus.TAGGED
    assert loaded.pages["page_0001"].complexity_flags == ["ghost_table"]
    assert loaded.pages["page_0002"].figures == []
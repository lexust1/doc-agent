# tests/test_manifest_manager.py
import json
import threading
from pathlib import Path

import pytest

from doc_agent.infrastructure.storage import LocalStorageManager
from doc_agent.infrastructure.manifest_manager import LocalManifestManager
from doc_agent.schemas.manifest import PageStatus, GlobalStatus


@pytest.fixture
def storage(tmp_path):
    """Provide a fresh LocalStorageManager rooted in a temp directory."""
    return LocalStorageManager(base_dir=tmp_path)


class TestInitManifest:
    def test_creates_new_manifest(self, storage):
        """First call writes a manifest with the given page count.
        doc_id is derived from the source PDF filename stem.
        """
        pdf_path = Path("source.pdf")
        doc_id = pdf_path.stem          # "source"
        manager = LocalManifestManager(storage=storage, doc_id=doc_id)
        manager.init_manifest(source_pdf_path=pdf_path, total_pages=3)

        state = manager.state
        assert state.doc_id == "source"
        assert state.source_file == pdf_path
        assert state.total_pages == 3
        assert len(state.pages) == 3
        assert all(
            p.status == PageStatus.PENDING for p in state.pages.values()
        )
        # Check that file exists on disk
        assert storage.get_absolute_path("manifest.json").exists()

    def test_loads_existing_manifest(self, storage):
        """Second init loads from disk instead of overwriting."""
        pdf_path = Path("source.pdf")
        doc_id = pdf_path.stem

        # First manager initialises and modifies state
        manager = LocalManifestManager(storage=storage, doc_id=doc_id)
        manager.init_manifest(source_pdf_path=pdf_path, total_pages=2)
        manager.update_page_status("page_0001", PageStatus.TAGGED)

        # Create a fresh manager pointing to the same storage and doc_id
        manager2 = LocalManifestManager(storage=storage, doc_id=doc_id)
        manager2.init_manifest(source_pdf_path=pdf_path, total_pages=0)

        # Should have loaded the previous state, not the passed page count
        state2 = manager2.state
        assert state2.total_pages == 2
        assert state2.pages["page_0001"].status == PageStatus.TAGGED


class TestPageStatusUpdates:
    def test_update_single_page(self, storage):
        """update_page_status changes the status and persists."""
        pdf_path = Path("s.pdf")
        manager = LocalManifestManager(storage=storage, doc_id=pdf_path.stem)
        manager.init_manifest(pdf_path, total_pages=2)
        manager.update_page_status("page_0001", PageStatus.CLEANED)

        assert manager.state.pages["page_0001"].status == PageStatus.CLEANED
        # Re‑read from disk to confirm persistence
        data = json.loads(
            manager.storage.get_absolute_path("manifest.json").read_text()
        )
        assert data["pages"]["page_0001"]["status"] == "cleaned"

    def test_concurrent_updates_dont_corrupt(self, storage):
        """Multiple threads updating the same page leave valid state."""
        pdf_path = Path("s.pdf")
        manager = LocalManifestManager(storage=storage, doc_id=pdf_path.stem)
        manager.init_manifest(pdf_path, total_pages=1)

        def toggle():
            for _ in range(10):
                manager.update_page_status("page_0001", PageStatus.TAGGED)
                manager.update_page_status("page_0001", PageStatus.CLEANED)

        threads = [threading.Thread(target=toggle) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # The manifest file must be valid JSON and contain the page key
        manifest_path = manager.storage.get_absolute_path("manifest.json")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "page_0001" in data["pages"]
        assert data["pages"]["page_0001"]["status"] in ("tagged", "cleaned")
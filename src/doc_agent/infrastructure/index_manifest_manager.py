import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from doc_agent.schemas.index_manifest import IndexManifest
from doc_agent.infrastructure.storage import StorageManagerProtocol

logger = logging.getLogger(__name__)


class LocalIndexManifestManager:
    """Manages the indexing lifecycle manifest for a single document.

    Works identically to LocalManifestManager but for the indexing stage,
    reading and writing an index_manifest.json file alongside the main
    processing manifest.  The class keeps an in‑memory copy of the manifest
    and persists changes under a thread lock.
    """

    def __init__(self, storage: StorageManagerProtocol, doc_id: str) -> None:
        """Initialise the index manifest manager.

        Args:
            storage: Storage backend implementing StorageManagerProtocol.
            doc_id: Unique document identifier (filename without extension).
        """
        self.storage = storage
        self.doc_id = doc_id
        self.manifest_key = "index_manifest.json"

        self._lock = threading.Lock()
        self._state: Optional[IndexManifest] = None

    @property
    def state(self) -> IndexManifest:
        """Return the current index manifest, loading from disk once."""
        if self._state is None:
            self._state = self._load()
        return self._state

    def is_indexed(self) -> bool:
        """Return True if the document has already been fully indexed."""
        return self.state.indexed

    def mark_indexed(self, chunk_count: int) -> None:
        """Mark the document as successfully indexed into Qdrant.

        Args:
            chunk_count: Number of chunks that were upserted.
        """
        with self._lock:
            manifest = self.state
            manifest.indexed = True
            manifest.indexed_at = datetime.now(timezone.utc).isoformat()
            manifest.chunk_count = chunk_count
            self._save_unsafe()
            logger.info(
                f"[Index] Marked '{self.doc_id}' as indexed ({chunk_count} chunks)."
            )

    def _load(self) -> IndexManifest:
        """Load the index manifest from storage or return a fresh default.

        Returns:
            An IndexManifest instance.
        """
        path = self.storage.get_absolute_path(self.manifest_key)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return IndexManifest(**data)
            except Exception as e:
                logger.warning(
                    f"[Index] Failed to parse index manifest for {self.doc_id}: {e}"
                )
        return IndexManifest(doc_id=self.doc_id)

    def _save_unsafe(self) -> None:
        """Persist the current manifest to storage.

        Must be called inside a with self._lock block.
        """
        if self._state is None:
            return
        json_content = self._state.model_dump_json(indent=2)
        self.storage.save_text(key=self.manifest_key, content=json_content)
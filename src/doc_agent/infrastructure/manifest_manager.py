import json
import logging
from pathlib import Path
import threading
from typing import List, Optional

# Local module imports
from doc_agent.schemas.manifest import DocumentManifest, GlobalStatus, PageState, PageStatus
from doc_agent.infrastructure.storage import StorageManagerProtocol

# Initialize a module-level logger.
logger = logging.getLogger(__name__)

class LocalManifestManager:
    """State Machine for document processing lifecycle.

    Acts as a lightweight state database (similar to MongoDB). Manages 
    document state transitions safely using threading locks and 
    ensures data integrity via Pydantic validation.
    """

    def __init__(self, storage: StorageManagerProtocol, doc_id: str):
        """Initializes the Manifest Manager.

        Args:
            storage (StorageManagerProtocol): The storage implementation to use.
            doc_id (str): Unique identifier for the document.
        """
        self.storage = storage
        self.doc_id = doc_id
        self.manifest_key = f"manifest.json"
        
        # Thread lock to prevent race conditions during state updates
        self._lock = threading.Lock()
        self._state: Optional[DocumentManifest] = None

    @property
    def state(self) -> Optional[DocumentManifest]:
        """Returns a snapshot of the current manifest state safely."""
        with self._lock:
            return self._state

    def init_manifest(self, source_pdf_path: Path, total_pages: int = 0) -> None:
            """Initializes a new document manifest or loads an existing one.

            If a manifest file already exists in storage, it is loaded into memory.
            If the loaded manifest lacks pages and total_pages is provided, it 
            bootstraps the page states.

            Args:
                source_pdf_path (Path): Path to the original source PDF.
                total_pages (int): Total number of pages in the document.
            """
            with self._lock:
                manifest_path = self.storage.get_absolute_path(self.manifest_key)

                # Attempt to load existing manifest if not already in memory
                if manifest_path.exists() and self._state is None:
                    try:
                        data = json.loads(manifest_path.read_text(encoding="utf-8"))
                        self._state = DocumentManifest(**data)
                        logger.info(f"[Manifest] Loaded existing manifest for: {self.doc_id}")
                    except Exception as e:
                        logger.error(f"[Manifest] Failed to load manifest {self.doc_id}: {e}")

                # Bootstrap pages if state is new or pages are missing
                if self._state is None or (not self._state.pages and total_pages > 0):
                    
                    # Initialize pages dictionary: page_0001, page_0002, etc.
                    pages_dict = {
                        f"page_{i:04d}": PageState() for i in range(1, total_pages + 1)
                    }

                    if self._state is None:
                        # Create new manifest state
                        self._state = DocumentManifest(
                            doc_id=self.doc_id,
                            source_file=source_pdf_path,
                            total_pages=total_pages,
                            pages=pages_dict
                        )
                    else:
                        # Update existing state with discovered pages
                        self._state.pages = pages_dict
                        self._state.total_pages = total_pages

                    # Persist state
                    self._save_unsafe()
                    logger.info(f"[Manifest] Initialized/Updated manifest for: {self.doc_id} ({total_pages} pages)")

    def update_page_status(self, page_id: str, status: PageStatus) -> None:
        """Updates the processing status of a specific page.

        Args:
            page_id (str): The identifier of the page (e.g., 'page_001').
            status (PageStatus): The new status to be applied.
        """
        with self._lock:
            if self._state and page_id in self._state.pages:
                self._state.pages[page_id].status = status
                self._save_unsafe()
                logger.debug(f"[Manifest] {page_id} status updated to: {status}")
    
    def update_global_status(self, status: GlobalStatus) -> None:
        """Updates the overall processing status of the document.

        Args:
            status (GlobalStatus): The new global status to apply.
        """
        with self._lock:
            if self._state:
                self._state.global_status = status
                self._save_unsafe()
                logger.info(f"[Manifest] Global status updated to: {status.value}")

    def add_page_artifact(self, page_id: str, artifact_type: str, relative_key: str) -> None:
        """Registers a file artifact associated with a specific page.

        Args:
            page_id (str): The identifier of the page.
            artifact_type (str): Type of artifact (e.g., 'image', 'ocr_text').
            relative_key (str): Relative storage path to the artifact file.
        """
        with self._lock:
            if self._state and page_id in self._state.pages:
                self._state.pages[page_id].paths[artifact_type] = relative_key
                self._save_unsafe()
                logger.debug(f"[Manifest] Added {artifact_type} artifact for {page_id}")

    def add_page_figure(self, page_id: str, relative_key: str) -> None:
            """Registers an extracted figure image path associated with a specific page.

            Args:
                page_id (str): The identifier of the page.
                relative_key (str): Relative storage path to the figure file.
            """
            with self._lock:
                if self._state and page_id in self._state.pages:
                    if relative_key not in self._state.pages[page_id].figures:
                        self._state.pages[page_id].figures.append(relative_key)
                        self._save_unsafe()
                        logger.debug(f"[Manifest] Added figure {relative_key} for {page_id}")

    def get_pages_by_status(self, status: PageStatus) -> List[str]:
        """Retrieves a list of page IDs that match the specified status.

        Args:
            status (PageStatus): The status to filter by.

        Returns:
            List[str]: A list of page IDs matching the criteria.
        """
        with self._lock:
            if not self._state:
                return []
            return [
                p_id for p_id, p_state in self._state.pages.items()
                if p_state.status == status
            ]

    def set_aggregated_file(self, relative_key: str) -> None:
        """Registers the path to the final aggregated JSON document."""
        with self._lock:
            if self._state:
                self._state.aggregated_file = relative_key
                self._save_unsafe()
                logger.info(f"[Manifest] Registered aggregated file: {relative_key}")

    def save(self) -> None:
        """Safely persists the current state to storage."""
        with self._lock:
            self._save_unsafe()

    def _save_unsafe(self) -> None:
        """Internal method to serialize and save state.

        WARNING: This method does not acquire the lock. 
        Must be called within a 'with self._lock' block.
        """
        if self._state:
            # model_dump_json handles serialization of Pydantic models (Enums/Paths)
            json_content = self._state.model_dump_json(indent=2)
            self.storage.save_text(key=self.manifest_key, content=json_content)
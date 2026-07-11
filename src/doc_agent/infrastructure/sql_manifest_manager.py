import logging
from pathlib import Path
from typing import Optional

from psycopg import Connection
from psycopg_pool import ConnectionPool
from psycopg.types.json import Json

from doc_agent.schemas.manifest import DocumentManifest, PageState, GlobalStatus, PageStatus


logger = logging.getLogger(__name__)


class SQLManifestManager:
    """PostgreSQL‑backed manifest manager for cloud (RDS) using Psycopg 3."""

    _pool: Optional[ConnectionPool] = None

    @classmethod
    def setup(cls, database_url: str) -> None:
        """One‑time application‑level setup: pool + table.

        Args:
            database_url: PostgreSQL connection string.
        """
        if cls._pool is not None:
            return

        cls._pool = ConnectionPool(database_url, min_size=1, max_size=10)

        with cls._pool.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS document_manifests (
                    doc_id VARCHAR PRIMARY KEY,
                    source_file VARCHAR NOT NULL,
                    total_pages INTEGER DEFAULT 0,
                    global_status VARCHAR DEFAULT 'processing',
                    pages JSONB DEFAULT '{}',
                    aggregated_file VARCHAR,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def __init__(self, doc_id: str) -> None:
        """Document‑level constructor – fast, no DB calls.

        Args:
            doc_id: Unique document identifier (PDF stem).
        """
        if SQLManifestManager._pool is None:
            raise RuntimeError(
                "Call SQLManifestManager.setup(database_url) first"
            )
        self.doc_id = doc_id

    @property
    def state(self) -> Optional[DocumentManifest]:
        """Load the full manifest row for this document.

        Returns:
            DocumentManifest if the row exists, else None.
        """
        # Resolve the shared pool – fails fast if setup() wasn't called.
        pool = self._pool
        if pool is None:
            raise RuntimeError("setup() must be called before accessing state")

        # Fetch the row inside a transaction (auto‑committed / rolled back).
        with pool.connection() as conn:
            cur = conn.execute(
                "SELECT * FROM document_manifests WHERE doc_id = %s",
                (self.doc_id,),
            )
            row = cur.fetchone()

        if row is None:
            return None

        # The default row factory returns a plain tuple, so we need to
        # build a dictionary using the column names from the cursor description.
        cols = [desc[0] for desc in cur.description]
        data = dict(zip(cols, row))

        # psycopg 3 returns the JSONB column as a native Python dict.
        pages_raw = data["pages"]
        pages = {pid: PageState(**pdata) for pid, pdata in pages_raw.items()}

        return DocumentManifest(
            doc_id=data["doc_id"],
            source_file=Path(data["source_file"]),
            total_pages=data["total_pages"],
            global_status=GlobalStatus(data["global_status"]),
            pages=pages,
            aggregated_file=data.get("aggregated_file"),
        )

    def init_manifest(self, source_pdf_path: Path, total_pages: int = 0) -> None:
        """Create the manifest row or bootstrap pages if needed.

        Idempotent – if the row already exists with pages, nothing changes.

        Args:
            source_pdf_path: Path to the original source PDF.
            total_pages: Total number of pages to bootstrap (if missing).
        """
        pool = self._pool
        if pool is None:
            raise RuntimeError("setup() must be called first")

        # Build the initial pages dictionary (all PENDING).
        pages = {
            f"page_{i:04d}": PageState().model_dump()
            for i in range(1, total_pages + 1)
        } if total_pages > 0 else {}

        with pool.connection() as conn:
            # ON CONFLICT DO NOTHING makes the INSERT idempotent.
            conn.execute(
                """INSERT INTO document_manifests
                   (doc_id, source_file, total_pages, pages)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (doc_id) DO NOTHING""",
                (self.doc_id, str(source_pdf_path), total_pages, Json(pages)),
            )

            # Bootstrap pages only if they are currently empty.
            if total_pages > 0:
                conn.execute(
                    """UPDATE document_manifests
                       SET pages = %s, total_pages = %s
                       WHERE doc_id = %s AND (pages IS NULL OR pages = '{}'::jsonb)""",
                    (Json(pages), total_pages, self.doc_id),
                )

    def update_page_status(self, page_id: str, status: PageStatus) -> None:
        """Atomically update the status of one page in the JSONB column.

        Args:
            page_id: Page identifier (e.g. ``'page_0001'``).
            status: New processing status to set.
        """
        pool = self._pool
        if pool is None:
            raise RuntimeError("setup() must be called first")

        with pool.connection() as conn:
            # jsonb_set replaces only the nested 'status' field.
            conn.execute(
                """UPDATE document_manifests
                   SET pages = jsonb_set(pages, %s, %s::jsonb, true),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE doc_id = %s""",
                (
                    f"{{{page_id},status}}",
                    f'"{status.value}"',
                    self.doc_id,
                ),
            )

    def add_page_artifact(self, page_id: str, artifact_type: str, relative_key: str) -> None:
        """Add an artifact path to the page's paths dict inside the JSONB column.

        Args:
            page_id: Page identifier (e.g. ``'page_0001'``).
            artifact_type: Key for the artifact (e.g. ``'pdf'``, ``'clean_md'``).
            relative_key: Storage key (relative path) of the artifact.
        """
        pool = self._pool
        if pool is None:
            raise RuntimeError("setup() must be called first")

        with pool.connection() as conn:
            # jsonb_set inserts/updates the specific artifact key.
            conn.execute(
                """UPDATE document_manifests
                   SET pages = jsonb_set(
                       pages,
                       %s,
                       %s::jsonb,
                       true
                   ),
                   updated_at = CURRENT_TIMESTAMP
                   WHERE doc_id = %s""",
                (
                    f"{{{page_id},paths,{artifact_type}}}",
                    f'"{relative_key}"',
                    self.doc_id,
                ),
            )

    def add_page_figure(self, page_id: str, relative_key: str) -> None:
        """Append a figure path to the page's figures list, avoiding duplicates.

        Args:
            page_id: Page identifier (e.g. ``'page_0001'``).
            relative_key: Storage key (relative path) of the figure image.
        """
        pool = self._pool
        if pool is None:
            raise RuntimeError("setup() must be called first")

        with pool.connection() as conn:
            # The WHERE clause uses JSON containment to prevent duplicates:
            #   pages #> %s        – extract the figures array for this page
            #   ::jsonb            – cast to jsonb so @> works
            #   @> %s::jsonb       – check if the array already contains the value
            #   NOT (...)          – skip the UPDATE if it does
            # This is a single atomic operation; no select-then-check needed.
            conn.execute(
                """UPDATE document_manifests
                   SET pages = jsonb_insert(
                       pages,
                       %s,
                       %s::jsonb,
                       true
                   ),
                   updated_at = CURRENT_TIMESTAMP
                   WHERE doc_id = %s
                     AND NOT (pages #> %s)::jsonb @> %s::jsonb""",
                (
                    f"{{{page_id},figures,0}}",      # insert at start of array
                    f'"{relative_key}"',             # the figure path to insert
                    self.doc_id,
                    f"{{{page_id},figures}}",        # path to the figures array
                    f"[{relative_key}]",             # array containing the value to check
                ),
            )

    def get_pages_by_status(self, status: PageStatus) -> list[str]:
        """Return page IDs whose status matches the given value.

        Args:
            status: The page status to filter by.

        Returns:
            List of page IDs (e.g. ``['page_0001', 'page_0003']``).
        """
        pool = self._pool
        if pool is None:
            raise RuntimeError("setup() must be called first")

        with pool.connection() as conn:
            # jsonb_each(pages) returns (key, value) pairs.
            # j.value ->> 'status' extracts the text value of the status field.
            rows = conn.execute(
                """SELECT key FROM document_manifests,
                   jsonb_each(pages) AS j
                   WHERE doc_id = %s
                     AND j.value ->> 'status' = %s""",
                (self.doc_id, status.value),
            ).fetchall()

        return [row[0] for row in rows]

    def set_aggregated_file(self, relative_key: str) -> None:
        """Register the path to the aggregated JSON document.

        Args:
            relative_key: Storage key (relative path) of the aggregated file.
        """
        pool = self._pool
        if pool is None:
            raise RuntimeError("setup() must be called first")

        with pool.connection() as conn:
            conn.execute(
                """UPDATE document_manifests
                   SET aggregated_file = %s,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE doc_id = %s""",
                (relative_key, self.doc_id),
            )

    def update_global_status(self, status: GlobalStatus) -> None:
        """Update the overall processing status of the document.

        Args:
            status: New global status to set.
        """
        pool = self._pool
        if pool is None:
            raise RuntimeError("setup() must be called first")

        with pool.connection() as conn:
            conn.execute(
                """UPDATE document_manifests
                   SET global_status = %s,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE doc_id = %s""",
                (status.value, self.doc_id),
            )

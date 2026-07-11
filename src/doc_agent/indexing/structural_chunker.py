import hashlib
import logging
import re
from typing import List

from doc_agent.schemas.manifest import DocumentManifest
from doc_agent.schemas.aggregated_doc import AggregatedDocument
from doc_agent.schemas.vector_payload import VectorPayload, PayloadMetadata

logger = logging.getLogger(__name__)


class StructuralChunker:
    """
    Splits aggregated markdown documents into structural text chunks.

    Relies strictly on Markdown headers (H1, H2, H3, H4) to define
    boundaries and embeds physical page artifacts from the manifest
    for source citation.

    The class is intentionally kept as a lightweight holder of
    pre‑compiled regex patterns.  All chunking logic is contained
    in ``process_document``.
    """

    def __init__(self):
        # Pre‑compile regex patterns to avoid re‑compilation on every block.
        # The page anchor has the form <!-- page_XXXX --> inserted by the
        # document aggregator.
        self.page_pattern = re.compile(r"<!-- (page_\d+) -->")
        self.h1_pattern = re.compile(r"^#\s+(.+)$")
        self.h2_pattern = re.compile(r"^##\s+(.+)$")
        self.h3_pattern = re.compile(r"^###\s+(.+)$")
        self.h4_pattern = re.compile(r"^####\s+(.+)$")

    def _generate_chunk_id(
        self,
        doc_id: str,
        text: str,
        h1: str | None,
        h2: str | None,
        h3: str | None,
        h4: str | None,
    ) -> str:
        """Generate a stable, deterministic SHA‑256 hash for the chunk ID.

        The hash now includes the document identifier, the full chunk text,
        and the entire header hierarchy.  This prevents ID collisions when
        identical boilerplate text appears under different sections.
        """
        # Build a canonical string that uniquely identifies this chunk's
        # location in the document structure.
        header_path = "::".join(filter(None, [h1, h2, h3, h4]))
        content = f"{doc_id}::{header_path}::{text}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def process_document(
        self,
        agg_doc: AggregatedDocument,
        manifest: DocumentManifest,
    ) -> List[VectorPayload]:
        """Split an aggregated document into searchable chunks.

        The full markdown text is walked block‑by‑block.  A running
        buffer collects text until a new header (H1‑H4) is encountered,
        at which point the buffer is flushed as a single chunk.  Page
        anchors (``<!-- page_XXXX -->``) update the current page
        position and are stripped before the text reaches the chunk.

        Example:
        Given markdown::

            <!-- page_0001 -->
            # Section 1
            Intro text.

            ## 1.1 Subsection
            Details here.

        The function returns two ``VectorPayload`` objects (hashes are
        deterministic but shown here in abbreviated form for illustration):

        [
            VectorPayload(
                chunk_id="a1b2c3d4e5f67890",
                text="# Section 1\n\nIntro text.",
                metadata=PayloadMetadata(pages=["page_0001"], h1="Section 1")
            ),
            VectorPayload(
                chunk_id="f1e2d3c4b5a67890",
                text="## 1.1 Subsection\n\nDetails here.",
                metadata=PayloadMetadata(pages=["page_0001"], h1="Section 1", h2="1.1 Subsection")
            ),
        ]

        Args:
            agg_doc: The aggregated document to be chunked.
            manifest: The document manifest containing per‑page paths
                      and metadata used for source citation.

        Returns:
            A list of ``VectorPayload`` objects ready for embedding
            and insertion into Qdrant.
        """
        logger.info(f"[Chunker] Starting structural chunking for document: {agg_doc.doc_id}")

        chunks: List[VectorPayload] = []

        # Track the current structural context as we walk through blocks.
        # These are reset when a higher‑level header appears.
        current_page = "unknown"   # last seen page anchor
        curr_h1: str | None = None
        curr_h2: str | None = None
        curr_h3: str | None = None
        curr_h4: str | None = None

        # The text buffer accumulates blocks belonging to the current chunk.
        buffer: List[str] = []
        # Set of page IDs that contributed text to the current buffer.
        active_pages: set[str] = set()

        # Original source PDF filename, preserved for citation.
        source_pdf_path = str(manifest.source_file) if manifest.source_file else "unknown.pdf"

        # Split the aggregated text on blank lines – each block is a
        # paragraph, header line, table row, or page anchor.
        blocks = agg_doc.full_text.split("\n\n")

        def flush_buffer():
            """Package the accumulated text buffer into a single chunk."""
            if not buffer:
                return

            text_content = "\n\n".join(buffer).strip()
            if not text_content:
                return

            # Use the sorted list of pages that contributed to this chunk.
            # If no page was explicitly recorded, fall back to the last seen page.
            sorted_pages = sorted(list(active_pages)) if active_pages else [current_page]

            # Collect paths to rendered page images for frontend display.
            artifacts = {}
            for pid in sorted_pages:
                if pid in manifest.pages and 'png' in manifest.pages[pid].paths:
                    artifacts[pid] = manifest.pages[pid].paths['png']

            metadata = PayloadMetadata(
                doc_id=agg_doc.doc_id,
                source_pdf=source_pdf_path,
                pages=sorted_pages,
                page_artifacts=artifacts,
                h1=curr_h1,
                h2=curr_h2,
                h3=curr_h3,
                h4=curr_h4,
            )

            chunks.append(
                VectorPayload(
                    chunk_id=self._generate_chunk_id(
                        agg_doc.doc_id,
                        text_content,
                        curr_h1,
                        curr_h2,
                        curr_h3,
                        curr_h4,
                    ),
                    text=text_content,
                    metadata=metadata,
                )
            )

            # Reset the buffer and page tracking for the next chunk.
            buffer.clear()
            active_pages.clear()
            # The current page is still "active" even if no explicit anchor
            # appears in the next block.
            if current_page != "unknown":
                active_pages.add(current_page)

        # Main walk over the document blocks.
        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # page anchor detection:
            # The aggregator inserts invisible HTML comments to mark physical
            # page boundaries.  We extract the page ID and remove the comment
            # from the text so it does not appear in search results.
            page_match = self.page_pattern.search(block)
            if page_match:
                current_page = page_match.group(1)
                active_pages.add(current_page)
                block = self.page_pattern.sub("", block).strip()
                if not block:
                    # The block consisted solely of the page anchor – nothing
                    # to add to the buffer.
                    continue

            # header detection:
            # A markdown header starts a new structural section.
            # We flush the current buffer (if any) and start a fresh one
            # under the new header hierarchy.
            h1_match = self.h1_pattern.match(block)
            h2_match = self.h2_pattern.match(block)
            h3_match = self.h3_pattern.match(block)
            h4_match = self.h4_pattern.match(block)

            if h1_match or h2_match or h3_match or h4_match:
                flush_buffer()

                # Update the hierarchical context.  Lower‑level headers
                # are reset when a higher‑level header appears.
                if h1_match:
                    curr_h1 = h1_match.group(1)
                    curr_h2, curr_h3, curr_h4 = None, None, None
                elif h2_match:
                    curr_h2 = h2_match.group(1)
                    curr_h3, curr_h4 = None, None
                elif h3_match:
                    curr_h3 = h3_match.group(1)
                    curr_h4 = None
                elif h4_match:
                    curr_h4 = h4_match.group(1)

                buffer.append(block)
            else:
                # Ordinary block – accumulates under the current headers.
                buffer.append(block)

        # Flush any remaining text after the last header.
        flush_buffer()

        logger.info(f"[Chunker] Successfully generated {len(chunks)} payloads for {agg_doc.doc_id}")
        return chunks
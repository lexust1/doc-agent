import logging
from typing import Optional

from doc_agent.infrastructure.manifest_manager import LocalManifestManager
from doc_agent.infrastructure.storage import StorageManagerProtocol
from doc_agent.schemas.aggregated_doc import AggregatedDocument, PageContent

logger = logging.getLogger(__name__)


def aggregate_document(
    doc_id: str,
    manifest: LocalManifestManager,
    storage: StorageManagerProtocol
) -> Optional[AggregatedDocument]:
    """Aggregates all cleaned markdown pages into a single JSON structure.
    
    This function reads the processing manifest to locate all finalized 
    markdown pages for a given document. It compiles them into an 
    AggregatedDocument object and injects invisible HTML anchors 
    (e.g., <!-- page_0001 -->) to preserve physical boundaries for downstream 
    semantic chunking.

    Args:
        doc_id (str): The unique identifier for the document.
        manifest (LocalManifestManager): The state manager tracking page statuses.
        storage (StorageManagerProtocol): The interface for file system operations.

    Returns:
        Optional[AggregatedDocument]: The fully assembled document object, 
            or None if the manifest is empty or aggregation fails.
    """
    state = manifest.state
    if not state or not state.pages:
        logger.error(f"[Aggregator] Cannot aggregate {doc_id}: Manifest state is empty.")
        return None

    page_contents = []
    full_text_blocks = []

    # Ensure pages are processed in strict sequential order
    sorted_page_ids = sorted(state.pages.keys())

    logger.info(f"[Aggregator] Starting aggregation for {doc_id} ({len(sorted_page_ids)} pages).")

    for page_id in sorted_page_ids:
        page_meta = state.pages[page_id]
        clean_md_rel = page_meta.paths.get("clean_md")

        if not clean_md_rel:
            logger.warning(f"[Aggregator] Skipping {page_id}: 'clean_md' path is missing in manifest.")
            continue

        try:
            # Read the finalized markdown content via the storage protocol
            abs_path = storage.get_absolute_path(clean_md_rel)
            md_text = abs_path.read_text(encoding="utf-8")

            # Build the discrete page object
            page_contents.append(PageContent(page_id=page_id, markdown=md_text))

            # Inject the physical anchor for the chunker
            full_text_blocks.append(f"<!-- {page_id} -->\n{md_text}")

        except Exception as e:
            logger.error(f"[Aggregator] Failed to read or process markdown for {page_id}: {e}", exc_info=True)
            raise

    # Assemble the final data contract
    aggregated_doc = AggregatedDocument(
        doc_id=doc_id,
        total_pages=len(page_contents),
        pages=page_contents,
        full_text="\n\n".join(full_text_blocks)
    )

    # Persist the aggregated document to storage as JSON
    output_rel_path = f"05_aggregated/{doc_id}.json"
    json_content = aggregated_doc.model_dump_json(indent=2)
    storage.save_text(output_rel_path, json_content)

    logger.info(f"[Aggregator] Successfully saved aggregated document to {output_rel_path}.")

    return aggregated_doc
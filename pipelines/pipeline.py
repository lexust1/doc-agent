"""
End‑to‑end ingestion workflow: raw PDFs → chunked, indexed documents in Qdrant.

For each PDF found in the data/01_raw directory, this script:
  - loads the VLM healing prompt from prompts/ocr_healing.md
  - runs the per‑document processing (slice → tag → heal → aggregate)
  - checks the index manifest; if already indexed, skips
  - performs structural chunking of the aggregated text
  - saves payloads as JSON under 06_payloads
  - embeds and upserts into Qdrant (dense + BM25)
  - marks the document as indexed

The pipeline is safe to re‑run: idempotency is guaranteed at every stage.
"""

import logging
import sys
import json
from pathlib import Path

import boto3

from doc_agent.configs.settings import settings
from doc_agent.utils.logger import setup_logger

from doc_agent.ingestion.workflow import process_document
from doc_agent.infrastructure.storage import LocalStorageManager
from doc_agent.infrastructure.manifest_manager import LocalManifestManager
from doc_agent.infrastructure.index_manifest_manager import LocalIndexManifestManager
from doc_agent.indexing.structural_chunker import StructuralChunker
from doc_agent.indexing.embedder import Embedder
from doc_agent.indexing.qdrant_manager import QdrantManager

logger = logging.getLogger(__name__)


def main() -> None:
    """Main pipeline execution for document."""
    logger.info("=== STARTING PIPELINE ===")

    # Load the VLM healing system prompt.
    # It will be passed unchanged to every page's healing step.
    prompt_path = settings.PROMPTS_DIR / "ocr_healing.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at: {prompt_path}")

    system_prompt = prompt_path.read_text(encoding="utf-8")
    logger.info(f"Loaded system prompt from: {prompt_path.name}")

    # Discover the PDF files waiting to be ingested.
    raw_dir = settings.RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)

    # AWS-specific logic: pull source PDFs from S3 to local container volume before processing
    if settings.DEPLOYMENT_MODE == "aws":
        if not settings.AWS_S3_BUCKET:
            raise RuntimeError("AWS_S3_BUCKET must be set in .env when DEPLOYMENT_MODE=aws")
            
        logger.info("Cloud mode: Syncing source PDFs from S3...")
        s3_client = boto3.client("s3", region_name=settings.AWS_REGION)
        prefix = "01_raw/"
        
        try:
            response = s3_client.list_objects_v2(Bucket=settings.AWS_S3_BUCKET, Prefix=prefix)
            for obj in response.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".pdf"):
                    local_path = raw_dir / Path(key).name
                    if not local_path.exists():
                        logger.info(f"Downloading {key} from S3...")
                        s3_client.download_file(settings.AWS_S3_BUCKET, key, str(local_path))
        except Exception as e:
            logger.error(f"Failed to sync PDFs from S3: {e}")

    pdf_files = list(raw_dir.glob("*.pdf"))
    
    if not pdf_files:
        logger.warning(f"No PDF files found in {raw_dir}")
        return

    logger.info(f"Found {len(pdf_files)} documents in {raw_dir.name}/")

    # Cloud‑mode initialisation (one‑time, before any document).
    # Sets up the shared connection pool for RDS and verifies the table.
    if settings.DEPLOYMENT_MODE == "aws":
        if not settings.DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL must be set in .env when DEPLOYMENT_MODE=aws"
            )
        from doc_agent.infrastructure.sql_manifest_manager import SQLManifestManager
        SQLManifestManager.setup(settings.DATABASE_URL)
        logger.info("Cloud mode: SQLManifestManager pool initialised.")

    # Instantiate services that are shared across all documents.
    # These are expensive to create and can be reused safely.
    chunker = StructuralChunker()
    embedder = Embedder()
    qdrant = QdrantManager(embedder)
    # Ensure the target Qdrant collection exists (idempotent)
    qdrant.create_hybrid_collection(settings.QDRANT_COLLECTION_NAME)

    # Process each document one by one.
    # Errors on one document never stop the rest of the batch.
    for pdf_path in pdf_files:
        doc_id = pdf_path.stem
        logger.info(f"--- Processing document: {doc_id} ---")

        try:
            # Create a local storage handle for this document.
            # It points to the isolated workspace that process_document will use.
            workspace_dir = settings.PROCESSING_DIR / doc_id
            storage = LocalStorageManager(base_dir=workspace_dir)

            # Skip documents that have already been completely indexed
            index_manager = LocalIndexManifestManager(storage=storage, doc_id=doc_id)
            if index_manager.is_indexed():
                logger.info(f"Document '{doc_id}' already indexed – skipping.")
                continue

            # Run the full document processing pipeline.
            # This handles slicing, tagging, healing, and aggregation.
            # Idempotent – pages already done are skipped automatically.
            agg_doc = process_document(pdf_path, system_prompt)

            if agg_doc is None:
                logger.error(f"Processing failed for {doc_id} – no aggregated document returned.")
                continue

            # Reload the manifest so we have its current state for chunking.
            # The manifest already exists inside the workspace after processing.
            manifest = LocalManifestManager(storage=storage, doc_id=doc_id)
            manifest.init_manifest(source_pdf_path=pdf_path)
            state = manifest.state

            if not state:
                logger.error(f"Manifest state is empty for {doc_id} – cannot chunk.")
                continue
                    
            # Structural chunking: split the aggregated markdown into
            # searchable chunks with metadata.
            logger.info(f"Generating Vector Payloads for {doc_id}...")
            payloads = chunker.process_document(agg_doc, state)

            # Save the raw payloads as a JSON snapshot before embedding.
            # This serves two purposes:
            #   - Inspection / debugging – you can open the JSON to verify
            #     what text was chunked and what metadata it carries.
            #   - Reproducibility – if the embedder or Qdrant changes later,
            #     you can re‑index from this snapshot without re‑running the
            #     heavy processing (PDF slicing, Docling, VLM healing).
            payloads_dir = workspace_dir / "06_payloads"
            payloads_dir.mkdir(parents=True, exist_ok=True)

            # Convert each Pydantic model to a plain dictionary.
            # model_dump() produces JSON‑serialisable dicts, including
            # nested objects like PayloadMetadata.
            payloads_json = [payload.model_dump() for payload in payloads]

            out_file = payloads_dir / f"{doc_id}_payloads.json"
            out_file.write_text(
                json.dumps(payloads_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                f"Saved {len(payloads)} payloads to {out_file.relative_to(settings.PROJECT_ROOT)}"
            )

            # Embed the chunks and upsert them into Qdrant.
            # Both dense and BM25 sparse vectors are handled automatically.
            qdrant.upsert_payloads(
                settings.QDRANT_COLLECTION_NAME,
                payloads,
                batch_size=settings.EMBED_BATCH_SIZE,
            )

            # Mark the document as indexed so future runs skip it entirely
            index_manager.mark_indexed(len(payloads))

        except Exception as e:
            # Catch any unexpected error so the batch continues
            logger.error(f"Critical failure for {pdf_path.name}: {e}", exc_info=True)

    logger.info("=== PIPELINE FINISHED ===")


if __name__ == "__main__":
    # Configure the root logger before launching the pipeline
    setup_logger(name="")
    try:
        main()
    except Exception:
        logger.exception("Fatal error in pipeline – exiting.")
        sys.exit(1)
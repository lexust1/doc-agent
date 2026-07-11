import concurrent.futures
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Optional, Union


# Config
from doc_agent.configs.settings import settings

# Infrastructure
from doc_agent.infrastructure.storage import LocalStorageManager, S3StorageManager
from doc_agent.infrastructure.manifest_manager import LocalManifestManager 
from doc_agent.infrastructure.sql_manifest_manager import SQLManifestManager
from doc_agent.schemas.manifest import GlobalStatus, PageStatus, PageState
from doc_agent.schemas.aggregated_doc import AggregatedDocument

# Data Extractors
from doc_agent.ingestion.pdf_processor import slice_pdf_to_pages
from doc_agent.ingestion.content_extractor import parse_document
from doc_agent.ingestion.document_aggregator import aggregate_document

# AI Agents
from doc_agent.agents.ocr_healer import OCRHealerAgent

logger = logging.getLogger(__name__)


def create_managers(doc_id: str, pdf_path: Path) -> tuple:
    """
    Instantiate storage and manifest managers based on the current deployment environment.
    
    Args:
        doc_id (str): The unique identifier for the document being processed.
        pdf_path (Path): The file path to the source PDF document.
        
    Returns:
        tuple: A tuple containing the initialized storage manager and manifest manager.
        
    Raises:
        RuntimeError: If required cloud environment variables are missing in AWS mode.
    """
    # Define the local processing directory (required for physical PDF slicing in all modes)
    workspace_dir: Path = settings.PROCESSING_DIR / doc_id
    
    if settings.DEPLOYMENT_MODE == "aws":
        # Cloud mode: use S3 for artifacts and RDS (PostgreSQL) for state tracking
        if not settings.AWS_S3_BUCKET:
            raise RuntimeError("AWS_S3_BUCKET must be set in the environment when DEPLOYMENT_MODE=aws.")
            
        storage = S3StorageManager(
            bucket=settings.AWS_S3_BUCKET,
            region=settings.AWS_REGION,
            prefix=doc_id,
            base_dir=workspace_dir
        )
        
        manifest = SQLManifestManager(doc_id=doc_id)
    else:
        # Local mode: use local disk for both artifacts and state tracking
        storage = LocalStorageManager(base_dir=workspace_dir)
        manifest = LocalManifestManager(storage=storage, doc_id=doc_id)

    return storage, manifest


@dataclass
class PipelineContext:
    """Context object passed to every pipeline step.

    Holds all shared services and per‑document parameters so
    step functions receive everything they need as an argument,
    without depending on the orchestrator class internals.

    Attributes:
        doc_id: Unique document identifier (PDF filename stem).
        pdf_path: Absolute path to the source PDF.
        system_prompt: The VLM system prompt loaded from disk.
        storage: Local storage backend for this document.
        manifest: Page‑level state machine for idempotency.
        agent: The OCR healing agent (VLM client).
        orientation_model_path: Path to the ONNX orientation model.
    """

    doc_id: str
    pdf_path: Path
    system_prompt: str
    storage: Union[LocalStorageManager, S3StorageManager]
    manifest: Union[LocalManifestManager, SQLManifestManager]
    agent: OCRHealerAgent
    orientation_model_path: Path


def slice_pages(ctx: PipelineContext) -> None:
    """Ensure the source PDF is sliced into single‑page PDFs and PNGs.

    Initialises (or loads) the manifest, checks whether any page
    already has a PDF artifact, and if not performs physical slicing
    with rotation correction.  The resulting per‑page files are
    registered in the manifest.

    This function is idempotent – if slicing has already been done,
    it exits without repeating the work.

    Args:
        ctx: Pipeline context containing manifest, storage, and paths.
    """
    # Bootstrap the manifest (load existing or create blank slate)
    ctx.manifest.init_manifest(source_pdf_path=ctx.pdf_path)

    # Determine whether slicing is necessary
    state = ctx.manifest.state
    needs_slicing = (
        not state
        or not state.pages
        or not list(state.pages.values())[0].paths.get("pdf")
    )

    if not needs_slicing:
        logger.info("Slicing already complete – skipping.")
        return

    # Perform the actual slicing and rotation correction.
    # This generates:
    #   - 01_pages_pdf/page_XXXX.pdf  (single‑page PDF, upright)
    #   - 02_renders_png/page_XXXX_highres.png  (for VLM healing)
    logger.info(f"Starting physical slicing for {ctx.pdf_path.name}")
    pages_data_list = slice_pdf_to_pages(
        pdf_path=ctx.pdf_path,
        workspace_dir=ctx.storage.base_dir,   # document’s isolated workspace
        model_path=ctx.orientation_model_path,
    )

    # Re‑initialise the manifest now that we know the true page count. 
    # This replaces the temporary empty (or outdated) page dictionary
    # with a fresh one containing the correct number of PENDING pages.
    ctx.manifest.init_manifest(
        source_pdf_path=ctx.pdf_path, total_pages=len(pages_data_list)
    )

    # Register the generated artifacts in the manifest.
    # Paths are stored relative to the workspace so the manifest
    # remains portable across machines / directory renames.
    for page_data in pages_data_list:
        page_id = page_data["id"]
        rel_pdf = page_data["pdf"].relative_to(ctx.storage.base_dir)
        rel_png = page_data["png"].relative_to(ctx.storage.base_dir)
        ctx.storage.save_binary(rel_pdf, page_data["pdf"].read_bytes())
        ctx.storage.save_binary(rel_png, page_data["png"].read_bytes())
        ctx.manifest.add_page_artifact(page_id, "pdf", str(rel_pdf))
        ctx.manifest.add_page_artifact(page_id, "png", str(rel_png))

    logger.info(f"Slicing complete – {len(pages_data_list)} pages registered.")


def tag_pages(ctx: PipelineContext) -> None:
    """Run Docling extraction + semantic tagging on every page that needs it.

    Iterates over all pages whose status is PENDING, RENDERED, or FAILED,
    invokes Docling with XML tagging enabled, saves the tagged markdown,
    and registers any extracted figures in the manifest.  Pages that have
    already been tagged or cleaned are skipped.

    The operation is parallelised using a thread pool; the number of workers
    is controlled by settings.MAX_WORKERS.

    Args:
        ctx: Pipeline context with manifest, storage, and workspace path.
    """

    # Collect pages that require tagging
    pending_ids = ctx.manifest.get_pages_by_status(PageStatus.PENDING)
    rendered_ids = ctx.manifest.get_pages_by_status(PageStatus.RENDERED)
    failed_ids = ctx.manifest.get_pages_by_status(PageStatus.FAILED)
    all_target_ids = pending_ids + rendered_ids + failed_ids

    if not all_target_ids:
        logger.info("No pages require tagging – all already tagged or cleaned.")
        return

    logger.info(
        f"Starting parallel tagging for {len(all_target_ids)} page(s) "
        f"using {settings.MAX_WORKERS} worker(s)."
    )

    # Run per‑page tagging in a thread pool.
    # Each worker reads the page PDF, runs Docling, and writes the tagged markdown.
    # Errors are caught per‑page so a single failure does not block the remaining work.
    with concurrent.futures.ThreadPoolExecutor(max_workers=settings.MAX_WORKERS) as executor:
        futures = {
            executor.submit(_tag_single_page, ctx, page_id): page_id
            for page_id in all_target_ids
        }

        for future in concurrent.futures.as_completed(futures):
            page_id = futures[future]
            try:
                future.result()
            except Exception:
                logger.error(
                    f"Unhandled error while tagging {page_id} – marking as FAILED.",
                    exc_info=True,
                )
                ctx.manifest.update_page_status(page_id, PageStatus.FAILED)

    logger.info("Parallel tagging completed.")


def _tag_single_page(ctx: PipelineContext, page_id: str) -> None:
    """Extract and save tagged markdown for a single page.

    This function is intended to be called inside a thread pool.
    It does not return a value; side‑effects on the manifest are
    persisted immediately.

    Args:
        ctx: Pipeline context.
        page_id: Manifest page identifier (e.g. 'page_0001').
    """
    # Read the current page state and locate the source PDF
    state = ctx.manifest.state
    if not state or page_id not in state.pages:
        raise ValueError(f"Page {page_id} missing from manifest – cannot tag.")

    page_meta = state.pages[page_id]
    pdf_rel = page_meta.paths.get("pdf")
    if not pdf_rel:
        raise ValueError(f"Page {page_id} has no PDF path registered – run slice_pages first.")

    page_pdf = ctx.storage.get_absolute_path(pdf_rel)

    # Run Docling extraction with XML tagging enabled.
    # Figures are saved into a per‑page subdirectory for later reference.
    figures_dir = ctx.storage.base_dir / "05_figures" / page_id

    tagged_md, figure_paths = parse_document(
        file_path=page_pdf,
        do_formula_enrichment=True,
        generate_picture_images=True,
        do_ocr=False,
        image_output_dir=figures_dir,
    )

    # Persist the tagged markdown and register the generated figures.
    # Paths are stored relative to the workspace for portability.
    tagged_rel = f"03_md_tagged/{page_id}.md"
    ctx.storage.save_text(tagged_rel, tagged_md)
    ctx.manifest.add_page_artifact(page_id, "tagged_md", tagged_rel)
    
    for fig_path in figure_paths:
        rel_fig = fig_path.relative_to(ctx.storage.base_dir)
        ctx.manifest.add_page_figure(page_id, str(rel_fig))

    # Advance the page status to TAGGED
    ctx.manifest.update_page_status(page_id, PageStatus.TAGGED)
    logger.debug(f"Page {page_id} successfully tagged.")


def heal_pages(ctx: PipelineContext) -> None:
    """Run VLM semantic normalization on every page that is tagged.

    Iterates over all pages with status TAGGED, sends the tagged
    markdown and the corresponding rendered PNG to the healing
    agent, and saves the resulting clean markdown.  Pages that
    have already been cleaned or failed are skipped.

    The operation is parallelised using a thread pool; the number
    of workers is controlled by settings.MAX_WORKERS.

    Args:
        ctx: Pipeline context with manifest, storage, and agent.
    """
    # Collect pages that are ready for healing
    tagged_ids = ctx.manifest.get_pages_by_status(PageStatus.TAGGED)

    if not tagged_ids:
        logger.info("No pages require healing – all already cleaned.")
        return

    logger.info(
        f"Starting parallel healing for {len(tagged_ids)} page(s) "
        f"using {settings.MAX_WORKERS} worker(s)."
    )

    # Run per‑page healing in a thread pool.
    with concurrent.futures.ThreadPoolExecutor(max_workers=settings.MAX_WORKERS) as executor:
        futures = {
            executor.submit(_heal_single_page, ctx, page_id): page_id
            for page_id in tagged_ids
        }

        for future in concurrent.futures.as_completed(futures):
            page_id = futures[future]
            try:
                future.result()
            except Exception:
                logger.error(
                    f"Unhandled error while healing {page_id} – marking as FAILED.",
                    exc_info=True,
                )
                ctx.manifest.update_page_status(page_id, PageStatus.FAILED)

    logger.info("Parallel healing completed.")


def _heal_single_page(ctx: PipelineContext, page_id: str) -> None:
    """Heal a single page using the VLM agent.

    This function is intended to be called inside a thread pool.
    It does not return a value; side‑effects on the manifest are
    persisted immediately.

    Args:
        ctx: Pipeline context.
        page_id: Manifest page identifier (e.g. 'page_0001').
    """
    # Read the current page state and locate the required inputs
    state = ctx.manifest.state
    if not state or page_id not in state.pages:
        raise ValueError(f"Page {page_id} missing from manifest – cannot heal.")

    page_meta = state.pages[page_id]
    tagged_rel = page_meta.paths.get("tagged_md")
    png_rel = page_meta.paths.get("png")

    if not tagged_rel:
        raise ValueError(f"Page {page_id} has no tagged markdown – run tag_pages first.")
    if not png_rel:
        raise ValueError(f"Page {page_id} has no rendered PNG – run slice_pages first.")

    tagged_md_path = ctx.storage.get_absolute_path(tagged_rel)
    page_png_path = ctx.storage.get_absolute_path(png_rel)

    tagged_md_content = tagged_md_path.read_text(encoding="utf-8")

    # Call the VLM healing agent
    clean_md = ctx.agent.normalize_page(
        tagged_text=tagged_md_content,
        image_path=page_png_path,
        system_prompt=ctx.system_prompt,
    )

    # Persist the clean markdown
    clean_rel = f"04_md_clean/{page_id}.md"
    ctx.storage.save_text(clean_rel, clean_md)
    ctx.manifest.add_page_artifact(page_id, "clean_md", clean_rel)

    # Advance the page status to CLEANED
    ctx.manifest.update_page_status(page_id, PageStatus.CLEANED)
    logger.debug(f"Page {page_id} successfully healed.")


def aggregate_pages(ctx: PipelineContext) -> Optional[AggregatedDocument]:
    """Assemble all cleaned pages into a single aggregated document.

    Calls the existing document aggregator, which reads every page's
    clean markdown from storage, injects HTML page anchors, and wraps
    them in an ``AggregatedDocument``.  The resulting JSON is saved
    to disk, the manifest is updated with its path, and the document
    is marked as completed.

    Args:
        ctx: Pipeline context with manifest, storage, and doc_id.

    Returns:
        The assembled ``AggregatedDocument``, or ``None`` if
        aggregation fails.
    """
    logger.info(f"Starting aggregation for {ctx.doc_id}")

    # Run the existing aggregation logic
    agg_doc = aggregate_document(
        doc_id=ctx.doc_id,
        manifest=ctx.manifest,
        storage=ctx.storage,
    )

    if agg_doc is None:
        logger.error(f"Aggregation failed for {ctx.doc_id} – marking as FAILED.")
        ctx.manifest.update_global_status(GlobalStatus.FAILED)
        return None

    # Register the aggregated file and mark the whole document as completed
    aggregated_rel = f"05_aggregated/{ctx.doc_id}.json"
    ctx.manifest.set_aggregated_file(aggregated_rel)
    ctx.manifest.update_global_status(GlobalStatus.COMPLETED)

    logger.info(f"Aggregation complete – saved to {aggregated_rel}")
    return agg_doc


def process_document(
    pdf_path: Path,
    system_prompt: str,
) -> Optional[AggregatedDocument]:
    """Run all processing steps for a single document.

    Creates the isolated workspace, initialises services, and
    executes the sequence: slice → tag → heal → aggregate.

    Args:
        pdf_path: Absolute path to the source PDF.
        system_prompt: The VLM system prompt loaded from disk.

    Returns:
        The assembled ``AggregatedDocument``, or ``None`` if an
        unrecoverable failure occurs.
    """
    doc_id = pdf_path.stem
    workspace_dir = settings.PROCESSING_DIR / doc_id

    # Initialise the local storage and manifest
    storage, manifest = create_managers(doc_id, pdf_path)

    # Initialise the VLM agent (shared across all steps)
    agent = OCRHealerAgent(
        api_key=settings.NANOGPT_API_KEY,
        base_url=settings.NANOGPT_BASE_URL,
        model_name=settings.TARGET_MODEL,
    )

    # Path to the ONNX orientation model
    orientation_model_path = settings.PROJECT_ROOT / "models" / "page_orientation.onnx"

    # Build the pipeline context
    ctx = PipelineContext(
        doc_id=doc_id,
        pdf_path=pdf_path,
        system_prompt=system_prompt,
        storage=storage,
        manifest=manifest,
        agent=agent,
        orientation_model_path=orientation_model_path,
    )

    # Run the pipeline steps sequentially
    try:
        slice_pages(ctx)
        tag_pages(ctx)
        heal_pages(ctx)
        agg_doc = aggregate_pages(ctx)
    except Exception:
        logger.error(
            f"Unrecoverable error while processing {doc_id}.", exc_info=True
        )
        manifest.update_global_status(GlobalStatus.FAILED)
        return None

    return agg_doc

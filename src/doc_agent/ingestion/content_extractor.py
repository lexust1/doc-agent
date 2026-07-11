import logging
from pathlib import Path
from typing import Optional

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc.document import PictureItem

# Import our semantic tagger
from doc_agent.ingestion.semantic_tagger import generate_tagged_markdown

# Initialize a module-level logger. 
# It will inherit configuration from the Root logger set up in the pipeline.
logger = logging.getLogger(__name__)


def parse_document(
        file_path: Path,
        do_formula_enrichment: bool = True, 
        generate_picture_images: bool = True,
        do_ocr: bool = False,
        image_output_dir: Optional[Path] = None
        ) -> tuple[str, list[Path]]:
    """Parses a PDF document, isolates images, and returns XML-tagged text along with figure paths.
    
    Args:
        file_path (Path): The absolute or relative path to the PDF file.
        do_formula_enrichment (bool): If True, enables formula decoding.
        generate_picture_images (bool): If True, isolates figures from text flow.
        do_ocr (bool): If False, forces the parser to rely solely on the embedded 
            PDF text layer, ignoring text visually embedded in images/drawings.
        image_output_dir (Optional[Path]): If provided, extracted images will be 
            saved to this directory as PNG files.

    Returns:
        tuple[str, list[Path]]: A tuple containing the extracted tagged markdown text 
            and a list of absolute Paths to the saved figure images.
            
    Raises:
        Exception: If Docling fails to process the document.
    """
    logger.debug(f"Starting advanced document extraction for: {file_path.name}")

    try:
        # 1. Configure Pipeline Options
        # PdfPipelineOptions allows fine-tuning of machine learning models 
        # and heuristics applied during the PDF processing.
        pipeline_options = PdfPipelineOptions()
        
        # Enable or disable mathematical formula recognition.
        # If True, Docling attempts to decode equation images into LaTeX formats.
        pipeline_options.do_formula_enrichment = do_formula_enrichment
        
        # Enable or disable picture isolation.
        # If True, the parser will extract figures, charts, and diagrams from the layout.
        pipeline_options.generate_picture_images = generate_picture_images
        
        # Disable OCR (Optical Character Recognition) by default.
        # This prevents the parser from reading labels inside diagrams/schematics 
        # as standard text, which often results in disconnected "spaghetti text".
        pipeline_options.do_ocr = do_ocr
        
        # 2. Initialize the Document Converter
        # DocumentConverter handles various formats. Here, we bind our specific 
        # pipeline options exclusively to the PDF input format.
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        
        # 3. Execute the Conversion
        # This is the heavy-lifting phase: parsing the visual structure, applying ML models,
        # and building the internal document graph (DoclingDocument).
        result = converter.convert(file_path)
        
        # 4. Process and Save Extracted Images
        saved_figure_paths = []
        if image_output_dir and generate_picture_images:
            # Ensure the output directory exists, creating parent folders if necessary
            image_output_dir.mkdir(parents=True, exist_ok=True)
            img_count = 0
            
            # Iterate through all parsed elements in the document graph.
            # The _level variable indicates nesting depth, but we only need the elements.
            for element, _level in result.document.iterate_items():
                
                # Verify 3 specific conditions:
                # 1. The element is classified as a PictureItem.
                # 2. It contains image metadata.
                # 3. It holds a valid, generated PIL.Image object.
                if isinstance(element, PictureItem) and element.image is not None and element.image.pil_image is not None:
                    img_count += 1
                    
                    # Format the filename using the original PDF stem and an incremental index
                    img_filename = f"{file_path.stem}_image_{img_count}.png"
                    img_path = image_output_dir / img_filename
                    
                    # Open the target file in binary write mode and save via PIL
                    with img_path.open("wb") as fp:
                        element.image.pil_image.save(fp, format="PNG")
                    
                    # Track the successfully written absolute paths for storage in the manifest
                    saved_figure_paths.append(img_path)
            
            logger.info(f"Saved {img_count} images to {image_output_dir.name}/")
        
        # 5. Export Results
        # Convert the internal document structure into a semantically anchored XML-like format.
        # This replaces the native Markdown export to provide strict boundaries for the VLM.
        tagged_markdown_text = generate_tagged_markdown(result.document)

        logger.info(f"Successfully extracted and tagged {len(tagged_markdown_text)} characters from {file_path.name}")
        
        return tagged_markdown_text, saved_figure_paths

    except Exception as e:
        # Log the error with the specific filename to assist in debugging batch processing failures
        logger.error(f"Internal error while parsing {file_path.name} with advanced options: {e}")
        # Re-raise the exception so the calling orchestration code can handle the failure appropriately
        raise
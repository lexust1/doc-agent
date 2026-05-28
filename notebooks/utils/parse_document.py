import logging
from pathlib import Path
from typing import List, Optional, Tuple

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc.document import PictureItem

# Initialize a module-level logger. 
# It will inherit configuration from the Root logger set up in the pipeline.
logger = logging.getLogger(__name__)


def parse_document_base(file_path: Path) -> str:
    """Parses a PDF document and returns its content as a Markdown string.
    
    This function strictly handles basic text extraction.

    Args:
        file_path (Path): The absolute or relative path to the PDF file.

    Returns:
        str: The extracted text formatted in Markdown.
        
    Raises:
        Exception: If Docling fails to process the document.
    """
    logger.debug(f"Starting base document extraction for: {file_path.name}")

    try:
        # Initialize the base Docling document converter without special options
        converter = DocumentConverter()
        
        # Execute the conversion process on the target file
        result = converter.convert(file_path)
        
        # Extract the parsed document structure and export it to Markdown format
        markdown_text = result.document.export_to_markdown()

        logger.info(f"Successfully extracted {len(markdown_text)} characters from {file_path.name}")
        return markdown_text

    except Exception as e:
        logger.error(f"Internal error while parsing {file_path.name}: {e}")
        # Re-raise the exception so the orchestrating pipeline is aware of the failure
        raise


def parse_document_formulas_and_drawing(
    file_path: Path,
    do_formula_enrichment: bool = True, 
    generate_picture_images: bool = True,
    do_ocr: bool = False,
    image_output_dir: Optional[Path] = None
) -> str:
    """Parses a PDF document with advanced visual pipeline options enabled.
    
    This experimental version attempts to decode mathematical formulas, 
    isolate schematic drawings/images, and optionally save them to disk.
    It intentionally disables OCR to prevent aggressive artifacts 
    (e.g., disconnected "spaghetti text" from labels inside diagrams).

    Args:
        file_path (Path): The absolute or relative path to the PDF file.
        do_formula_enrichment (bool): If True, enables formula decoding.
        generate_picture_images (bool): If True, isolates figures from text flow.
        do_ocr (bool): If False, forces the parser to rely solely on the embedded 
            PDF text layer, ignoring text visually embedded in images/drawings.
        image_output_dir (Optional[Path]): If provided, extracted images will be 
            saved to this directory as PNG files.

    Returns:
        str: The extracted text formatted in Markdown.
        
    Raises:
        Exception: If Docling fails to process the document.
    """
    logger.debug(f"Starting advanced document extraction for: {file_path.name}")

    try:
        # Initialize specific pipeline options for PDF processing
        pipeline_options = PdfPipelineOptions()
        
        # Formula Enrichment
        pipeline_options.do_formula_enrichment = do_formula_enrichment
        
        # Picture Isolation
        pipeline_options.generate_picture_images = generate_picture_images
        
        # Disable OCR to stop reading labels inside schematics
        pipeline_options.do_ocr = do_ocr
        
        # Initialize the Docling document converter
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        
        # Execute the conversion process on the target file
        result = converter.convert(file_path)
        
        if image_output_dir and generate_picture_images:
            image_output_dir.mkdir(parents=True, exist_ok=True)
            img_count = 0
            
            # Iterate through the document elements to find pictures
            for element, _level in result.document.iterate_items():
                if isinstance(element, PictureItem) and element.image is not None and element.image.pil_image is not None:
                    img_count += 1
                    img_filename = f"{file_path.stem}_image_{img_count}.png"
                    img_path = image_output_dir / img_filename
                    
                    # Save the PIL image to disk
                    with img_path.open("wb") as fp:
                        element.image.pil_image.save(fp, format="PNG")
            
            logger.info(f"Saved {img_count} images to {image_output_dir.name}/")
        
        # Extract the parsed document structure and export it to Markdown format
        markdown_text = result.document.export_to_markdown()

        logger.info(f"Successfully extracted {len(markdown_text)} characters from {file_path.name} (Advanced Pipeline)")
        return markdown_text

    except Exception as e:
        logger.error(f"Internal error while parsing {file_path.name} with advanced options: {e}")
        # Re-raise the exception so the orchestrating pipeline is aware of the failure
        raise

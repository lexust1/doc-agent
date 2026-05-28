import logging
from pathlib import Path
import pypdfium2 as pdfium

# Initialize a module-level logger.
logger = logging.getLogger(__name__)

def extract_page_image(pdf_path: Path, output_dir: Path) -> Path:
    """Extracts the first page of a PDF as a high-resolution PNG image.
    
    Simplified for single-page document processing.
    Utilizes the Google Chrome PDFium engine for extremely fast rendering.

    Args:
        pdf_path (Path): The absolute or relative path to the source PDF file.
        output_dir (Path): The directory where the extracted image will be saved.

    Returns:
        Path: The absolute or relative path to the saved PNG image.

    Raises:
        Exception: If the PDFium engine fails to load or render the document.
    """
    logger.debug(f"Starting image extraction for {pdf_path.name}")

    pdf = None

    try:
        # 1. Load the PDF Document
        pdf = pdfium.PdfDocument(str(pdf_path))

        # 2. Render the First Page (index 0)
        page = pdf[0]
        
        # scale=3 (int) provides ~216 DPI (crisp text and tables for the VLM)
        bitmap = page.render(scale=3)
        pil_image = bitmap.to_pil()

        # 3. Export Result
        output_dir.mkdir(parents=True, exist_ok=True)
        # Simplified filename for single-page logic
        output_file = output_dir / f"{pdf_path.stem}_highres.png"

        with output_file.open("wb") as fp:
            pil_image.save(fp, format="PNG")

        logger.info(f"Successfully saved high-res image to: {output_file.name}")
        
        return output_file

    except Exception as e:
        logger.error(f"Internal error while extracting image with pypdfium2: {e}")
        raise
        
    finally:
        # Ensure the PDF resource is closed cleanly to free memory
        if pdf is not None:
            pdf.close()
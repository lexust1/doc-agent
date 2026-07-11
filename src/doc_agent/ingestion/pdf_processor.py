import logging
from pathlib import Path
from typing import Dict, List, Any

import numpy as np
import onnxruntime as ort
import pypdfium2 as pdfium
from PIL import Image

logger = logging.getLogger(__name__)

# Global class mapping for the PP-LCNet_x1_0_doc_ori model
ROTATION_CLASSES = [0, 90, 180, 270]


def detect_page_orientation(pil_image: Image.Image, session: ort.InferenceSession) -> int:
    """
    Determines the page rotation angle (0, 90, 180, 270) using a 4-class ONNX model.
    
    Uses the PP-LCNet_x1_0_doc_ori architecture which natively understands 
    all four document orientations by analyzing the layout, tables, and lines.
    
    Args:
        pil_image (Image.Image): The rendered page image as a PIL Image.
        session (ort.InferenceSession): The initialized ONNX runtime session.
        
    Returns:
        int: The detected rotation angle in degrees (0, 90, 180, or 270).
    """
    img_cls = pil_image.convert('RGB')
    
    # 1. Preprocess the image to match the LCNet expected input (224x224)
    img_cls = img_cls.resize((224, 224), Image.Resampling.LANCZOS)
    img_data = np.array(img_cls).astype('float32') / 255.0
    
    # 2. Standard ImageNet normalization (required by PP-LCNet)
    mean = np.array([0.485, 0.456, 0.406], dtype='float32')
    std = np.array([0.229, 0.224, 0.225], dtype='float32')
    img_data = (img_data - mean) / std
    
    # 3. Transpose to NCHW format (Batch, Channels, Height, Width)
    img_data = np.transpose(img_data, (2, 0, 1))
    img_data = np.expand_dims(img_data, axis=0)

    # 4. Perform inference (4 classes)
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: img_data})
    
    # 5. Extract the class ID and map to the corresponding rotation angle
    class_id = int(np.argmax(outputs[0]))
    
    return ROTATION_CLASSES[class_id]


def slice_pdf_to_pages(pdf_path: Path, workspace_dir: Path, model_path: Path) -> List[Dict[str, Any]]:
    """
    Slices a multi-page PDF into individual PDF files, detects orientation,
    and physically auto-rotates both the PNGs and PDFs to 0 degrees.

    Args:
        pdf_path (Path): Path to the source multi-page PDF document.
        workspace_dir (Path): The isolated workspace directory for this document.
        model_path (Path): Path to the 4-class ONNX orientation model (PP-LCNet).

    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing the paths to 
        the generated artifacts and the normalized rotation data:
        [
            {
                "id": "page_0001", 
                "pdf": Path(...), 
                "png": Path(...),
                "rotation": 0,  # Always 0 because it's physically fixed
                "original_rotation": 0 | 90 | 180 | 270
            }, ...
        ]
    """
    logger.info(f"Starting physical slicing and auto-rotation for: {pdf_path.name}")

    # Create target directories within the workspace
    pdf_dir = workspace_dir / "01_pages_pdf"
    png_dir = workspace_dir / "02_renders_png"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)

    # Initialize the orientation model session once for the entire document
    logger.info("Loading 4-class ONNX orientation model...")
    session = ort.InferenceSession(str(model_path), providers=['CPUExecutionProvider'])

    pages_data = []
    source_pdf = None

    try:
        source_pdf = pdfium.PdfDocument(str(pdf_path))
        total_pages = len(source_pdf)
        logger.info(f"Detected {total_pages} pages in document.")

        for i in range(total_pages):
            page_num = i + 1
            page_id = f"page_{page_num:04d}"
            
            # Define output paths
            page_pdf_path = pdf_dir / f"{page_id}.pdf"
            page_png_path = png_dir / f"{page_id}_highres.png"

            # 1. Render the page as a high-resolution PNG for detection
            page = source_pdf[i]
            # scale=3 provides roughly 216-300 DPI, perfect for VLM OCR
            bitmap = page.render(scale=3)
            pil_image = bitmap.to_pil()
            
            # 2. Detect visual rotation
            detected_angle = detect_page_orientation(pil_image, session)

            # 3. Apply physical rotation to PNG if needed
            if detected_angle != 0:
                logger.info(f"Fixing visual rotation for {page_id}: {detected_angle}° -> 0°")
                # Negative angle rotates it back to 0. expand=True prevents cropping.
                pil_image = pil_image.rotate(detected_angle, expand=True)

            # Save the physically corrected PNG
            with page_png_path.open("wb") as fp:
                pil_image.save(fp, format="PNG")

            # 4. Extract and apply physical rotation to the standalone PDF page
            new_pdf = pdfium.PdfDocument.new()
            new_pdf.import_pages(source_pdf, [i])
            
            if detected_angle != 0:
                pdf_page = new_pdf[0]
                current_rot = pdf_page.get_rotation()
                # Subtract the detected angle to normalize to 0
                new_pdf_rotation = (current_rot - detected_angle) % 360
                pdf_page.set_rotation(new_pdf_rotation)

            new_pdf.save(str(page_pdf_path))
            new_pdf.close()

            # 5. Store the artifact paths and normalized metadata
            pages_data.append({
                "id": page_id,
                "pdf": page_pdf_path,
                "png": page_png_path,
                "rotation": 0,  # Now always 0 as the file is fixed
                "original_rotation": detected_angle
            })
            
            logger.debug(f"Successfully processed {page_id} (Fixed from {detected_angle}°)")

        logger.info(f"Completed slicing. Generated {len(pages_data)} normalized page bundles.")
        return pages_data

    except Exception as e:
        logger.error(f"Failed to slice PDF {pdf_path.name}: {e}", exc_info=True)
        raise

    finally:
        # Prevent memory leaks by explicitly closing the C/C++ underlying resources
        if source_pdf is not None:
            source_pdf.close()
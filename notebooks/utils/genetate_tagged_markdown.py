import logging
from pathlib import Path
from typing import Optional, Union

# Initialize module-level logger for granular tracking of the tagging process.
logger = logging.getLogger(__name__)

def generate_tagged_markdown(
    doc, 
    output_path: Optional[Union[str, Path]] = None
) -> Union[Path, str]:
    """
    Transforms a Docling AST into a semantically anchored XML-like format.

    The function iterates over all document elements (paragraphs, headings,
    tables, list items, etc.) in logical reading order. Each element is wrapped
    in a unique tag like `<paragraph_1>` and `</paragraph_1>`, where the numeric
    suffix ensures every element can be individually referenced. 

    The resulting string can be either returned directly or written to a file.
    The format is useful for semantic anchoring.

    Args:
        doc: A Docling document object.
        output_path (Optional[Union[str, Path]]): File path where the tagged
            output should be saved. If `None` (default), the content is only
            returned as a string. 

    Returns:
        str: The full tagged Markdown content as a single string.  

    Example:
        <title_1>
        Introduction
        </title_1>
        <paragraph_2>
        This document describes ...
    """
    logger.info("Initiating hybrid semantic tagging via explicit attribute extraction...")
    
    tagged_lines = []
    counters = {}

    # iterate_items() traverses nodes in logical reading order.
    for item, level in doc.iterate_items():
        
        # Extract native label
        base_label = item.label.value if hasattr(item.label, 'value') else str(item.label)
        
        # Update unique ID
        counters[base_label] = counters.get(base_label, 0) + 1
        tag_name = f"{base_label}_{counters[base_label]}"
        
        node_content = ""
        
        # 1. TABLE PROCESSING (Pure Markdown)
        # TableItem has no export_to_markdown, but it does provide DataFrame export.
        if base_label == "table" and hasattr(item, "export_to_dataframe"):
            try:
                df = item.export_to_dataframe()
                node_content = df.to_markdown(index=False)
            except Exception as e:
                logger.warning(f"Table markdown conversion failed for {tag_name}: {e}")
                node_content = getattr(item, "text", "")
                
        # 2. LIST PROCESSING
        # This is what Docling does internally during full export.
        elif base_label == "list_item":
            text = getattr(item, 'text', "")
            marker = getattr(item, 'marker', "")
            # If a marker exists (e.g., "5."), prepend it to the text.
            if marker and not text.startswith(marker):
                node_content = f"{marker} {text}"
            else:
                node_content = text
                
        # 3. ALL OTHER TEXT (Headings, paragraphs)
        else:
            node_content = getattr(item, 'text', "")
            if not node_content:
                node_content = getattr(item, 'orig', "")
                
        if node_content:
            tagged_lines.append(f"<{tag_name}>\n{node_content.strip()}\n</{tag_name}>\n\n")

    logger.info(f"Tagging complete. Generated {sum(counters.values())} unique semantic anchors.")
    
    full_content = "".join(tagged_lines)

    if output_path:
        artifact_path = Path(output_path)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(full_content, encoding="utf-8")
        logger.info(f"Anchored MD artifact successfully persisted at: {artifact_path}")

    return full_content
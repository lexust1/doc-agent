import logging
from typing import Any

# Initialize a module-level logger. 
# It will inherit configuration from the Root logger set up in the pipeline.
logger = logging.getLogger(__name__)


def generate_tagged_markdown(doc: Any) -> str:
    """Transforms the Docling AST into a semantically anchored XML-like format.
    
    This function iterates through the extracted document tree and wraps each 
    semantic block (e.g., text, headers, lists, tables) in unique XML-like tags. 
    This provides strict boundaries for downstream LLM processing.

    Args:
        doc (Any): The parsed Docling document object representing the AST.

    Returns:
        str: The extracted text structured with XML anchors (e.g., <text_1>).
        
    Raises:
        Exception: If the AST traversal or Markdown conversion fails.
    """
    logger.debug("Initiating hybrid semantic tagging via explicit attribute extraction...")
    
    tagged_lines = []
    counters = {}

    try:
        # iterate_items() ensures traversal of nodes in logical reading order.
        for item, level in doc.iterate_items():
            
            # Extract the native label (e.g., 'table', 'list_item', 'text')
            base_label = item.label.value if hasattr(item.label, 'value') else str(item.label)
            
            # Update the unique ID counter for the current label
            counters[base_label] = counters.get(base_label, 0) + 1
            tag_name = f"{base_label}_{counters[base_label]}"
            
            node_content = ""
            
            # 1. TABLE PROCESSING (Clean Markdown)
            # TableItem lacks export_to_markdown, but supports export_to_dataframe.
            if base_label == "table" and hasattr(item, "export_to_dataframe"):
                try:
                    df = item.export_to_dataframe()
                    node_content = df.to_markdown(index=False)
                except Exception as e:
                    logger.warning(f"Table markdown conversion failed for {tag_name}: {e}")
                    node_content = getattr(item, "text", "")
                    
            # 2. LIST ITEM PROCESSING
            # Reproduces the native Docling behavior for full exports.
            elif base_label == "list_item":
                text = getattr(item, 'text', "")
                marker = getattr(item, 'marker', "")
                
                # If a marker exists (e.g., "5."), prepend it to the text
                if marker and not text.startswith(marker):
                    node_content = f"{marker} {text}"
                else:
                    node_content = text
                    
            # 3. STANDARD TEXT PROCESSING (Headers, Paragraphs, etc.)
            else:
                node_content = getattr(item, 'text', "")
                if not node_content:
                    node_content = getattr(item, 'orig', "")
                    
            # Wrap the extracted content in the generated XML tags
            if node_content:
                tagged_lines.append(f"<{tag_name}>\n{node_content.strip()}\n</{tag_name}>\n\n")

        logger.info(f"Tagging complete. Generated {sum(counters.values())} unique semantic anchors.")
        
        full_content = "".join(tagged_lines)
        return full_content

    except Exception as e:
        logger.error(f"Internal error during semantic tagging: {e}")
        raise
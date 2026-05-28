import difflib
from IPython.display import display, Markdown

def display_diff(text_before: str, text_after: str, fromfile: str = "Before", tofile: str = "After"):
    """
    Generates and renders a compact unified diff between two strings in Jupyter Markdown.

    Args:
        text_before (str): The original text content (raw parsing).
        text_after (str): The modified text content (LLM healed).
        fromfile (str): Label for the source text in the diff header.
        tofile (str): Label for the target text in the diff header.
    """
    # Calculate differences line by line
    diff = difflib.unified_diff(
        text_before.splitlines(),
        text_after.splitlines(),
        fromfile=fromfile,
        tofile=tofile,
        lineterm=''
    )
    
    diff_text = '\n'.join(diff)
    
    if diff_text:
        display(Markdown(f"```diff\n{diff_text}\n```"))
    else:
        display(Markdown("> **No changes detected between versions.**"))
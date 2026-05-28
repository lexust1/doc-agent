import base64
from pathlib import Path


def encode_image_to_base64(file_path: Path) -> str:
    """Reads an image file from disk and encodes it to a Base64 string.
    
    This function handles the safe opening and reading of the binary file,
    preparing it for transport in JSON payloads for Vision-Language Models.

    Args:
        file_path (Path): The path to the target image file.

    Returns:
        str: The image data encoded as a UTF-8 Base64 string.
    """
    with file_path.open("rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")
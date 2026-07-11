import logging
import base64
from pathlib import Path

from openai import OpenAI
from doc_agent.schemas.llm_contracts import NormalizationResult

# Initialize a module-level logger
logger = logging.getLogger(__name__)


class OCRHealerAgent:
    """Agent responsible for semantic normalization of OCR text using Vision-Language Models."""

    def __init__(self, api_key: str, base_url: str, model_name: str = "openai/gpt-5-mini"):
        """Initializes the VLM Agent with API credentials and model routing.
        
        Args:
            api_key (str): The API key for the LLM service.
            base_url (str): The base URL for the API endpoint.
            model_name (str): The target Vision-Language Model to use.
        """
        self.model_name = model_name
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        logger.info(f"OCRHealerAgent initialized with model: {self.model_name}")

    def _encode_image_to_base64(self, file_path: Path) -> str:
        """Reads an image file from disk and encodes it to a Base64 string."""
        with file_path.open("rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def normalize_page(self, tagged_text: str, image_path: Path, system_prompt: str) -> str:
        """Processes the raw tagged text using the VLM to correct structural artifacts.
        
        Args:
            tagged_text (str): The raw text extracted by Docling, wrapped in XML anchors.
            image_path (Path): Path to the high-resolution PNG render of the page.
            system_prompt (str): The strict instructional prompt for the VLM (Native CoT).

        Returns:
            str: The fully normalized and cleaned Markdown text.
            
        Raises:
            Exception: If the API call fails or the Pydantic parsing is rejected.
        """
        logger.debug(f"Starting healing process for image: {image_path.name}")
        
        try:
            base64_image = self._encode_image_to_base64(image_path)
            
            # Constructing the multimodal payload (Text + Image)
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": f"Raw Tagged Markdown for processing:\n\n{tagged_text}"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}",
                                "detail": "high"  # Forces high-res mode, critical for formulas
                            }
                        }
                    ]
                }
            ]

            # Execute the API call using the stable .parse() method for structured output
            response = self.client.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                temperature=0.0,  # Zero creativity, maximum determinism
                response_format=NormalizationResult,
            )

            # The result is automatically deserialized into our Pydantic model
            normalized_data = response.choices[0].message.parsed
            logger.info("Healing complete. Successfully parsed structured output from VLM.")
            
            return normalized_data.clean_markdown

        except Exception as e:
            logger.error(f"VLM inference failed for {image_path.name}. Error: {e}", exc_info=True)
            raise
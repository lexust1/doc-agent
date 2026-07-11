import logging
from pathlib import Path
from typing import List, Union

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

from doc_agent.configs.settings import settings

logger = logging.getLogger(__name__)


class Embedder:
    """BGE-M3 ONNX embedding service.

    This class loads the tokenizer and ONNX session once at instantiation
    and reuses them for all subsequent calls.  The model path is read from
    the project settings.

    Typical usage::

        embedder = Embedder()
        vectors = embedder.embed(["Some text", "Another text"])
        # vectors.shape == (2, 1024), L2‑normalised
    """

    def __init__(self, model_path: Union[str, Path] = settings.EMBEDDING_MODEL_DIR) -> None:
        """Initialise the BGE‑M3 ONNX embedding service.

        Args:
            model_path: Path to the directory containing model.onnx,
                tokenizer.json, etc.  Defaults to settings.EMBEDDING_MODEL_DIR.
        """
        model_path = Path(model_path)

        logger.info(f"Loading BGE-M3 tokenizer from: {model_path}")
    
        # Load the tokenizer (vocabulary + special tokens)
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        logger.info(f"Tokenizer loaded – vocab size: {self.tokenizer.vocab_size}")

        # Use CoreML acceleration on macOS if available, otherwise CPU
        providers = ["CPUExecutionProvider"]
        if "CoreMLExecutionProvider" in ort.get_available_providers():
            providers = ["CoreMLExecutionProvider"] + providers

        # Create the ONNX inference session (no GPU required)
        self.session = ort.InferenceSession(
            str(model_path / "model.onnx"),
            providers=providers,
        )
        logger.info(f"ONNX session created – providers: {self.session.get_providers()}")

    def embed(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """Generate dense embeddings for a list of texts (chunks).

        Args:
            texts (List[str]): Input text chunks.
            batch_size (int, optional): Maximum number of texts per ONNX call.
                Defaults to 32.

        Returns:
            np.ndarray: L2‑normalised array of shape (len(texts), 1024).
        """
        if not texts:
            raise ValueError("texts must be non-empty.")

        all_vectors: List[np.ndarray] = []

        # Process texts in batches to control memory usage
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            logger.debug(f"Processing batch {i}-{i + len(batch) - 1} of {len(texts)} texts")

            # Tokenize with padding and truncation (max 8192 tokens per input)
            inputs = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=8192,
                return_tensors="np",
            )

            # Run the ONNX model and extract the CLS token (dense representation)
            outputs = self.session.run(None, dict(inputs))
            last_hidden = outputs[0]                     # shape: (batch, seq_len, 1024)
            cls_raw = last_hidden[:, 0, :]                # first token: CLS

            # L2-normalise so that inner product = cosine similarity
            norms = np.linalg.norm(cls_raw, axis=1, keepdims=True)
            cls_normalised = cls_raw / norms

            all_vectors.append(cls_normalised)

        result = np.concatenate(all_vectors, axis=0)
        logger.info(f"Successfully embedded {len(texts)} texts – output shape: {result.shape}")
        return result
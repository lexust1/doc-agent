import logging
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    SparseVectorParams,
    Modifier,
    PointStruct,
)

from doc_agent.configs.settings import settings
from doc_agent.indexing.embedder import Embedder
from doc_agent.schemas.vector_payload import VectorPayload

logger = logging.getLogger(__name__)


class QdrantManager:
    """Manages Qdrant collections and the indexing of vector payloads.

    This class is responsible for the write path: creating hybrid
    collections and upserting document chunks together with their
    dense embeddings.

    Typical usage:

        embedder = Embedder()
        manager = QdrantManager(embedder)
        manager.create_hybrid_collection("pue_chunks")
        manager.upsert_payloads("pue_chunks", payloads)
    """

    def __init__(
        self,
        embedder: Embedder,
        url: str = settings.QDRANT_URL,
        api_key: Optional[str] = settings.QDRANT_API_KEY,
    ) -> None:
        """Initialise the Qdrant manager with an embedder and connection.

        Args:
            embedder: Embedder instance used to generate dense vectors.
            url: Qdrant server URL. Defaults to settings.QDRANT_URL.
            api_key: Optional API key. Defaults to settings.QDRANT_API_KEY.
        """
        self.embedder = embedder

        # Create a client connected to local (or remote) Qdrant instance
        self.client = QdrantClient(url=url, api_key=api_key)
        logger.info(f"Connected to Qdrant at {url}")


    def create_hybrid_collection(
        self,
        collection_name: str,
        vector_size: int = 1024,
        distance: Distance = Distance.DOT,
    ) -> None:
        """Create a collection with dense and auto-BM25 sparse vector support.

        If the collection already exists the operation is skipped.

        Args:
            collection_name: Name of the collection to create.
            vector_size: Dimensionality of dense vectors (BGE-M3 = 1024).
            distance: Distance metric for dense vectors (DotProduct).
        """
        # Check existence to allow idempotent re-runs
        if self.client.collection_exists(collection_name):
            logger.info(f"Collection '{collection_name}' already exists – skipping creation.")
            return

        # Create collection with dense vector config and BM25 sparse vector config.
        # The BM25 sparse vectors are generated automatically by Qdrant from the text field.
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=distance),
            sparse_vectors_config={
                "bm25": SparseVectorParams(modifier=Modifier.IDF)
            },
        )
        logger.info(
            f"Collection '{collection_name}' created "
            f"(dense: {vector_size}d/{distance}, sparse: BM25 IDF)."
        )

    def upsert_payloads(
        self,
        collection_name: str,
        payloads: List[VectorPayload],
        batch_size: int = 32,
    ) -> None:
        """Embed and upload a list of VectorPayload objects into a Qdrant collection.

        The text field of each payload is embedded via the embedder.
        The full payload (text + metadata) is stored as Qdrant payload.

        Args:
            collection_name: Target collection name.
            payloads: List of VectorPayload objects to index.
            batch_size: Number of texts to embed in one ONNX call.
        """
        if not payloads:
            logger.warning("Empty payload list – nothing to upsert.")
            return

        # Extract all texts and embed them in a single call (batched internally)
        texts = [p.text for p in payloads]
        vectors = self.embedder.embed(texts, batch_size=batch_size)

        # Build Qdrant points with deterministic IDs and original payload data
        points = []
        for payload, vector in zip(payloads, vectors):
            # Convert hex chunk_id to 64‑bit integer for idempotent upserts
            point_id = int(payload.chunk_id, 16)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector.tolist(),
                    payload={
                        "text": payload.text,
                        **payload.metadata.model_dump(),
                    },
                )
            )

        # Perform the upsert; wait=True ensures the operation is durable before returning
        self.client.upsert(
            collection_name=collection_name,
            points=points,
            wait=True,
        )
        logger.info(
            f"Upserted {len(points)} points into collection '{collection_name}'."
        )
import logging
from collections import Counter
from typing import List, Dict, Any, Optional

from qdrant_client import QdrantClient, models

from doc_agent.configs.settings import settings
from doc_agent.indexing.embedder import Embedder

logger = logging.getLogger(__name__)


class HybridSearcher:
    """Performs hybrid (dense + BM25) search over a Qdrant collection.

    This class handles the read path: taking a user query, embedding it
    for dense search, constructing a sparse vector for BM25 search, and
    merging results with Reciprocal Rank Fusion.

    Typical usage::

        embedder = Embedder()
        searcher = HybridSearcher(embedder)
        results = searcher.search("допустимое сечение заземляющего проводника",
                                   "pue_hybrid_test",
                                   limit=5)
    """

    def __init__(
        self,
        embedder: Embedder,
        url: str = settings.QDRANT_URL,
        api_key: Optional[str] = settings.QDRANT_API_KEY,
    ) -> None:
        """Initialise the searcher with an embedder and Qdrant connection.

        Args:
            embedder: Embedder instance for dense query embedding.
            url: Qdrant server URL. Defaults to settings.QDRANT_URL.
            api_key: Optional API key. Defaults to settings.QDRANT_API_KEY.
        """
        self.embedder = embedder

        # Create a client connected to the Qdrant instance
        self.client = QdrantClient(url=url, api_key=api_key)
        logger.info(f"HybridSearcher connected to Qdrant at {url}")

    def search(
        self,
        query: str,
        collection_name: str,
        limit: int = 5,
        dense_limit: int = 10,
        sparse_limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Execute a hybrid search combining dense and BM25 retrieval.

        The query text is embedded for dense search, tokenised for sparse
        search, and the results are fused with Reciprocal Rank Fusion.

        Args:
            query: Natural language query text.
            collection_name: Name of the Qdrant collection to query.
            limit: Number of final results to return after fusion.
            dense_limit: Number of candidates to fetch from dense search.
            sparse_limit: Number of candidates to fetch from BM25 search.

        Returns:
            List of dictionaries, each containing keys:
                - score (float): Fusion score.
                - text (str): Chunk text.
                - metadata (dict): All payload fields except text.
        """
        # Build the dense embedding for semantic similarity.
        # This captures the overall meaning of the query, even if the
        # exact wording differs from the stored chunks.
        dense_vec = self._embed_query(query)

        # Build a sparse vector for keyword matching.
        # This helps find exact references like article numbers ("1.7.2")
        # or technical terms that may not be well captured by embeddings.
        sparse_vec = self._build_sparse_vector(query)

        # Execute a single hybrid query using Qdrant's prefetch mechanism.
        # Two independent searches run in parallel:
        #   1. Dense search (semantic) over the dense vector index.
        #   2. Sparse search (lexical) over the BM25 index.
        # Their results are then fused with Reciprocal Rank Fusion (RRF),
        # which gives each document a score based on its rank in each list
        # rather than its absolute similarity value.  This prevents one
        # retrieval method from dominating the other.
        hits = self.client.query_points(
            collection_name=collection_name,
            prefetch=[
                # Prefetch 1: dense (semantic)
                models.Prefetch(
                    query=dense_vec,
                    limit=dense_limit,   # get more candidates than needed for better fusion
                ),
                # Prefetch 2: sparse (BM25 lexical)
                models.Prefetch(
                    query=sparse_vec,
                    using="bm25",         # use the sparse vector index named "bm25"
                    limit=sparse_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,                  # final number of results after fusion
            with_payload=True,            # return the full payload with each hit
        )

        # Transform the raw Qdrant hits into a simpler dictionary format.
        # The payload contains the chunk text and all metadata fields;
        # we separate them for convenience.
        results = []
        for hit in hits.points:
            payload = hit.payload or {}
            # All fields except "text" are treated as metadata
            metadata = {k: v for k, v in payload.items() if k != "text"}
            results.append({
                "score": hit.score,
                "text": payload.get("text", ""),
                "metadata": metadata,
            })

        logger.info(f"Hybrid search returned {len(results)} results for query: '{query}'")
        return results

    def _embed_query(self, query: str) -> List[float]:
        """Embed a single query text and return the dense vector as a list."""
        # The embedder works on lists; wrap the query in a single‑element list
        # and extract the first (only) result.
        vec = self.embedder.embed([query])
        return vec[0].tolist()

    def _build_sparse_vector(self, query: str) -> models.SparseVector:
        """Tokenise the query and build a sparse vector for BM25 search.

        This method mimics the tokenisation that Qdrant performed at
        indexing time (using the same tokeniser from BGE‑M3).  Each
        token ID is treated as a dimension, and its count (term frequency)
        is used as the weight.  This allows Qdrant to match the query
        tokens against the pre‑computed BM25 statistics in the collection.
        """
        # Tokenise with the same tokenizer used for dense embeddings.
        # This ensures the token IDs are consistent between indexing and
        # query time.
        tokens = self.embedder.tokenizer.encode(query)
        token_counts = Counter(tokens)

        # Build a sparse vector: list of indices (token IDs) and their
        # corresponding values (term frequencies).
        indices = list(token_counts.keys())
        values = [float(token_counts[i]) for i in indices]

        return models.SparseVector(indices=indices, values=values)
import logging
from typing import Optional

from openai import OpenAI

from doc_agent.configs.settings import settings
from doc_agent.retrieval.hybrid_searcher import HybridSearcher
from doc_agent.schemas.llm_contracts import AnswerResult

logger = logging.getLogger(__name__)


class AnswerGeneratorAgent:
    """Generates strictly sourced answers using the Regulatory RAG Engine.

    This agent retrieves relevant chunks via hybrid search, formats them
    as structured context, and calls a reasoning LLM with a system prompt
    that enforces extraction‑only behaviour and a Pydantic output contract.
    """

    def __init__(self, searcher: HybridSearcher) -> None:
        """Initialise the AnswerGeneratorAgent.

        Args:
            searcher: A configured HybridSearcher instance.
        """
        self.searcher = searcher
        self.client = OpenAI(
            api_key=settings.NANOGPT_API_KEY,
            base_url=settings.NANOGPT_BASE_URL,
        )
        self.model = settings.TARGET_MODEL
        self.collection_name = settings.QDRANT_COLLECTION_NAME

    def generate(
        self,
        question: str,
        system_prompt: str,
        top_k: int = 5,
    ) -> AnswerResult:
        """Generate a fully sourced answer for a given engineering question.

        Args:
            question: The user's query.
            system_prompt: The system prompt controlling the LLM behaviour.
            top_k: Number of chunks to retrieve and present to the LLM.

        Returns:
            An AnswerResult containing the answer text and a list of cited sources.
        """
        # 1. Retrieve relevant chunks from the vector database
        results = self.searcher.search(
            question,
            collection_name=self.collection_name,
            limit=top_k,
            dense_limit=top_k * 2,
            sparse_limit=top_k * 2,
        )

        if not results:
            logger.warning("No chunks retrieved for question: %s", question[:80])
            return AnswerResult(
                answer="Не найдено ни одного релевантного фрагмента.",
                sources=[],
            )

        # 2. Build a structured context block (using the shared helper)
        context = self._build_context(results)

        # 3. Prepare the LLM messages
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Контекст:\n\n{context}\n\nВопрос: {question}",
            },
        ]

        # 4. Call the model with strict structured output
        logger.info("Calling LLM for question: %s", question[:80])
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=messages,
            temperature=0.0,
            response_format=AnswerResult,
        )

        parsed: Optional[AnswerResult] = response.choices[0].message.parsed
        if parsed is None:
            logger.error("LLM returned invalid structured output.")
            return AnswerResult(
                answer="Ошибка: модель не вернула структурированный ответ.",
                sources=[],
            )

        logger.info(
            "Answer generated – %d chars, %d sources cited.",
            len(parsed.answer),
            len(parsed.sources),
        )
        return parsed
    
    def generate_from_chunks(
        self,
        chunks: list,
        question: str,
        system_prompt: str,
    ) -> AnswerResult:
        """Generate an answer from pre‑retrieved chunks.

        This is used by the AgenticAnswerAgent to pass in its own
        chunk collection without going through the searcher.

        Args:
            chunks: List of dicts with keys 'text' and 'metadata',
                    exactly as returned by HybridSearcher.search().
            question: The user's question.
            system_prompt: The system prompt for answer generation.

        Returns:
            An AnswerResult containing the answer and cited sources.
        """
        if not chunks:
            return AnswerResult(
                answer="Не найдено ни одного релевантного фрагмента.",
                sources=[],
            )

        # Use the same context‑building logic as generate()
        context = self._build_context(chunks)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Контекст:\n\n{context}\n\nВопрос: {question}",
            },
        ]

        logger.info("Calling LLM with %d pre‑retrieved chunks.", len(chunks))
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=messages,
            temperature=0.0,
            response_format=AnswerResult,
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            logger.error("LLM returned invalid structured output.")
            return AnswerResult(
                answer="Ошибка: модель не вернула структурированный ответ.",
                sources=[],
            )
        return parsed
    
    def _build_context(self, chunks: list) -> str:
        """Format chunks into the structured context block for the LLM.

        Args:
            chunks: List of dicts with 'text' and 'metadata'.

        Returns:
            A single string with source labels, ready for the prompt.
        """
        parts = []
        for idx, chunk in enumerate(chunks, start=1):
            meta = chunk["metadata"]
            text = chunk["text"]
            pages = ", ".join(meta.get("pages", []))
            doc = meta.get("doc_id", "")
            h1 = meta.get("h1", "")
            h2 = meta.get("h2", "")
            h3 = meta.get("h3", "")
            h4 = meta.get("h4", "")
            section = " / ".join(filter(None, [h1, h2, h3, h4]))
            parts.append(
                f"[{idx}] Документ {doc}, страницы {pages}, раздел {section}\n{text}"
            )
        return "\n\n".join(parts)
"""Decomposes complex questions into searchable sub‑queries."""

import logging
from typing import Optional

from openai import OpenAI

from doc_agent.configs.settings import settings
from doc_agent.schemas.llm_contracts import DecomposedQuery

logger = logging.getLogger(__name__)


class QueryDecomposer:
    """
    Analyses a user question and, if multi‑hop, breaks it into
    independent sub‑questions that the retriever can handle separately.
    """

    def __init__(self) -> None:
        # Initialise the OpenAI client using project settings.
        # The same API key and base URL are used for all LLM calls.
        self.client = OpenAI(
            api_key=settings.NANOGPT_API_KEY,
            base_url=settings.NANOGPT_BASE_URL,
        )
        self.model = settings.TARGET_MODEL

        # Load the decomposition prompt from its version‑controlled file.
        # This prompt instructs the LLM to analyse the question and
        # produce a list of sub‑queries when the question spans multiple
        # sections or topics.
        prompt_path = settings.PROMPTS_DIR / "query_decomposition.md"
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def decompose(self, question: str) -> DecomposedQuery:
        """
        Decompose a possibly complex question into sub‑queries.

        Args:
            question: The user's original question.

        Returns:
            A DecomposedQuery with at least one sub‑query.
        """
        # Build the message list: the system prompt (which defines the
        # decomposition logic) and the user's question.
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": question},
        ]

        # Call the LLM with zero temperature for deterministic behaviour.
        # The response is parsed into a DecomposedQuery Pydantic model.
        logger.debug("Decomposing question: %s", question[:80])
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=messages,
            temperature=0.0,
            response_format=DecomposedQuery,
        )

        parsed: Optional[DecomposedQuery] = response.choices[0].message.parsed
        if parsed is None or not parsed.sub_queries:
            # If the LLM returned an empty result or parsing failed,
            # fall back to treating the original question as a single
            # sub‑query.  This ensures the pipeline always has something
            # to retrieve with.
            logger.warning("Decomposer returned empty; falling back to original.")
            return DecomposedQuery(
                is_complex=False,
                sub_queries=[{"text": question, "reason": "Original query"}],
            )

        logger.info(
            "Decomposed into %d sub‑query(ies) (complex=%s).",
            len(parsed.sub_queries), parsed.is_complex,
        )
        return parsed
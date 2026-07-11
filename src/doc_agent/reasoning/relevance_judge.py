"""Judge that evaluates the relevance of retrieved chunks for a given query."""

import logging
from pathlib import Path
from typing import List, Dict, Any

from openai import OpenAI

from doc_agent.configs.settings import settings
from doc_agent.schemas.llm_contracts import RelevanceVerdict

logger = logging.getLogger(__name__)


class RelevanceJudge:
    """
    Evaluates how well a set of retrieved chunks answers a question.
    Uses a lightweight LLM call to assign a score and optionally
    rewrite the query for better retrieval.
    """

    def __init__(self) -> None:
        # Initialise the OpenAI client using project settings.
        # The same API key and base URL are used for all LLM calls.
        self.client = OpenAI(
            api_key=settings.NANOGPT_API_KEY,
            base_url=settings.NANOGPT_BASE_URL,
        )
        self.model = settings.TARGET_MODEL

        # Load the judge's system prompt from its version‑controlled file.
        # This keeps the prompt editable without touching Python code.
        prompt_path = settings.PROMPTS_DIR / "relevance_evaluation.md"
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def evaluate(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        threshold: int = 3,
    ) -> RelevanceVerdict:
        """
        Assess relevance of the provided chunks to the query.

        Args:
            query: The search query used to retrieve the chunks.
            chunks: Retrieved chunks, each with 'text' and 'metadata'.
            threshold: Minimum score considered acceptable (default 3).

        Returns:
            A RelevanceVerdict with score, reasoning, and possibly a
            rewritten query.
        """
        # Build compact summaries of the retrieved chunks for the LLM.
        # Only the first 300 characters are included — this is enough
        # for the judge to understand the chunk's topic without
        # consuming excessive context window.
        chunk_summaries = []
        for i, chunk in enumerate(chunks, 1):
            text_preview = chunk["text"][:300].replace("\n", " ")
            chunk_summaries.append(f"[{i}] {text_preview}...")

        # Combine the query and the chunk summaries into the user message.
        user_content = (
            f"Запрос: {query}\n\n"
            "Найденные фрагменты:\n" + "\n".join(chunk_summaries)
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        # Call the LLM with zero temperature for deterministic results.
        # The response_format is set to RelevanceVerdict so the API
        # returns a pre‑validated Pydantic object when successful.
        logger.debug("Calling RelevanceJudge for query: %s", query[:80])
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=messages,
            temperature=0.0,
            response_format=RelevanceVerdict,
        )

        verdict = response.choices[0].message.parsed
        if verdict is None:
            # This shouldn't happen with a well‑formed response_format,
            # but we protect against it to avoid a hard crash.
            logger.error("RelevanceJudge returned invalid structured output.")
            return RelevanceVerdict(score=1, reasoning="Invalid LLM output.")

        logger.info(
            "Relevance score for '%s': %d/5 (threshold %d)",
            query[:60], verdict.score, threshold,
        )
        return verdict
"""Verifies that every factual claim in a generated answer is directly
supported by the provided evidence chunks."""

import logging
from typing import List, Dict, Any, Optional

from openai import OpenAI

from doc_agent.configs.settings import settings
from doc_agent.schemas.llm_contracts import FaithfulnessReport

logger = logging.getLogger(__name__)


class FaithfulnessChecker:
    """
    Verifies that every factual claim in a generated answer is directly
    supported by the provided evidence chunks.
    """

    def __init__(self) -> None:
        # Initialise the OpenAI client using project settings.
        self.client = OpenAI(
            api_key=settings.NANOGPT_API_KEY,
            base_url=settings.NANOGPT_BASE_URL,
        )
        self.model = settings.TARGET_MODEL

        # Load the faithfulness checking prompt from its version‑controlled file.
        # This prompt instructs the LLM to compare each claim in the answer
        # against the provided evidence and list any unsupported statements.
        prompt_path = settings.PROMPTS_DIR / "faithfulness_check.md"
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def check(
        self,
        answer: str,
        chunks: List[Dict[str, Any]],
    ) -> FaithfulnessReport:
        """
        Check the faithfulness of an answer against evidence chunks.

        Args:
            answer: The generated answer text.
            chunks: The retrieved chunks used to produce the answer.

        Returns:
            A FaithfulnessReport indicating whether the answer is fully
            supported and listing any unsupported claims.
        """
        # Build a compact evidence block for the LLM.
        # Each chunk is truncated to 500 characters – enough to capture
        # the gist of the content without overflowing the context window.
        # Newlines are collapsed so the evidence reads as continuous text.
        evidence_parts = []
        for i, chunk in enumerate(chunks, 1):
            text = chunk["text"][:500].replace("\n", " ")
            evidence_parts.append(f"[{i}] {text}...")
        evidence = "\n".join(evidence_parts)

        # Combine the evidence and the answer into a single user message.
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    f"Фрагменты документов:\n{evidence}\n\n"
                    f"Проверяемый ответ:\n{answer}"
                ),
            },
        ]

        # Call the LLM with zero temperature for deterministic results.
        # The response is parsed into a FaithfulnessReport Pydantic model.
        logger.debug("Calling FaithfulnessChecker.")
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=messages,
            temperature=0.0,
            response_format=FaithfulnessReport,
        )

        report: Optional[FaithfulnessReport] = response.choices[0].message.parsed
        if report is None:
            # If the LLM returned invalid JSON, assume the answer is
            # not faithful to prevent unsupported claims from being shown.
            logger.error("FaithfulnessChecker returned invalid structured output.")
            return FaithfulnessReport(is_faithful=False)

        if report.is_faithful:
            logger.info("Answer is fully faithful.")
        else:
            logger.warning(
                "%d unsupported claim(s) found.", len(report.unsupported_claims)
            )
        return report
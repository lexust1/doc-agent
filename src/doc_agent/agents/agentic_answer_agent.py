"""Agentic RAG agent that iteratively retrieves and self‑corrects."""

import logging
from typing import List, Dict, Any

from doc_agent.configs.settings import settings
from doc_agent.agents.answer_generator import AnswerGeneratorAgent
from doc_agent.retrieval.hybrid_searcher import HybridSearcher
from doc_agent.reasoning.query_decomposer import QueryDecomposer
from doc_agent.reasoning.relevance_judge import RelevanceJudge
from doc_agent.schemas.llm_contracts import AnswerResult

logger = logging.getLogger(__name__)


class AgenticAnswerAgent:
    """
    Agent that answers a question by iteratively retrieving,
    judging relevance, retrying with rewritten queries, and
    finally verifying the answer's faithfulness to the evidence.
    """

    def __init__(
        self,
        searcher: HybridSearcher,
        answer_generator: AnswerGeneratorAgent,
    ) -> None:
        """Initialise the AgenticAnswerAgent.

        Args:
            searcher: A configured HybridSearcher instance.
            answer_generator: An AnswerGeneratorAgent instance.
        """
        self.searcher = searcher
        self.answer_generator = answer_generator
        self.decomposer = QueryDecomposer()
        self.judge = RelevanceJudge()
        # Lazy‑loaded faithfulness checker (initialised on first use)
        self._faithfulness_checker = None

    def generate(
        self,
        question: str,
        system_prompt: str,
        top_k: int = 5,
    ) -> AnswerResult:
        """Answer a question using the agentic retrieval loop.

        Args:
            question: User's query.
            system_prompt: System prompt for final answer generation.
            top_k: Number of chunks per retrieval call.

        Returns:
            An AnswerResult with answer and sources.
        """
        # 1. Decompose the question
        decomposed = self.decomposer.decompose(question)
        logger.info(
            "Decomposed into %d sub‑query(ies).", len(decomposed.sub_queries)
        )

        # 2. For each sub‑query, retrieve with relevance judging and retries
        all_chunks: List[Dict[str, Any]] = []
        seen_ids = set()

        for sub in decomposed.sub_queries:
            chunks = self._retrieve_with_judge(sub.text)
            for chunk in chunks:
                chunk_id = hash(chunk["text"])
                if chunk_id not in seen_ids:
                    seen_ids.add(chunk_id)
                    all_chunks.append(chunk)

        if not all_chunks:
            return AnswerResult(
                answer="Не найдено ни одного релевантного фрагмента.",
                sources=[],
            )

        # 3. Generate the draft answer from the collected chunks
        answer_result = self._generate_answer(all_chunks, question, system_prompt)

        # 4. Faithfulness self‑check – remove unsupported claims
        if self._faithfulness_checker is None:
            from doc_agent.reasoning.faithfulness_checker import FaithfulnessChecker
            self._faithfulness_checker = FaithfulnessChecker()

        report = self._faithfulness_checker.check(answer_result.answer, all_chunks)
        if not report.is_faithful:
            logger.warning(
                "Answer contains %d unsupported claim(s); removing them.",
                len(report.unsupported_claims),
            )
            cleaned_answer = answer_result.answer
            for claim in report.unsupported_claims:
                cleaned_answer = cleaned_answer.replace(claim.claim, "")
            answer_result.answer = cleaned_answer.strip()
        else:
            logger.info("Faithfulness check passed.")

        return answer_result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _retrieve_with_judge(self, query: str) -> List[Dict[str, Any]]:
        """Retrieve chunks for a query, with up to settings.AGENT_MAX_RETRIEVAL_ATTEMPTS.

        Returns the first result set that passes the relevance threshold,
        or the last result set if all attempts fail.
        """
        current_query = query
        last_results = []

        for attempt in range(1, settings.AGENT_MAX_RETRIEVAL_ATTEMPTS + 1):
            logger.debug(
                "Retrieval attempt %d for '%s'", attempt, current_query[:60]
            )
            results = self.searcher.search(
                current_query,
                collection_name=settings.QDRANT_COLLECTION_NAME,
                limit=5,
                dense_limit=10,
                sparse_limit=10,
            )
            last_results = results

            verdict = self.judge.evaluate(
                current_query, results, settings.AGENT_RELEVANCE_THRESHOLD
            )

            if verdict.score >= settings.AGENT_RELEVANCE_THRESHOLD:
                logger.info("Relevance %d/5 – keeping chunks.", verdict.score)
                return results

            logger.info("Relevance %d/5 – below threshold.", verdict.score)
            if verdict.suggested_query:
                current_query = verdict.suggested_query
            else:
                logger.warning("No suggested query provided; stopping retries.")
                break

        logger.warning("All retrieval attempts exhausted for '%s'.", query[:60])
        return last_results

    def _generate_answer(
        self,
        chunks: List[Dict[str, Any]],
        question: str,
        system_prompt: str,
    ) -> AnswerResult:
        """Generate the final answer using the provided chunks."""
        return self.answer_generator.generate_from_chunks(
            chunks, question, system_prompt
        )
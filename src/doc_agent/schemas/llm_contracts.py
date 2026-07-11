from pydantic import BaseModel, Field
from typing import List, Optional


class NormalizationResult(BaseModel):
    """
    Data contract for the VLM Agent response.
    Ensures that the LLM returns only the final, cleaned markdown text.
    """
    clean_markdown: str = Field(
        description="Final, structurally corrected Markdown text WITHOUT any XML tags."
    )


class SourceInfo(BaseModel):
    """
    Describes a single source that was cited in the final answer.
    Each source corresponds to an inline reference like [1] and contains
    the document identifier, page numbers, and section path.
    """
    index: int = Field(
        description="Number matching the inline [N] citation in the answer text."
    )
    doc_id: str = Field(
        description="Document identifier (filename without extension, e.g. 'pue_1.1-1.3')."
    )
    pages: str = Field(
        description="Comma‑separated page IDs (e.g. 'page_0005, page_0006')."
    )
    section: str = Field(
        description="Full hierarchical section path (h1 / h2 / h3 / h4 joined by ' / ')."
    )


class AnswerResult(BaseModel):
    """
    Data contract for the Regulatory RAG Engine response.
    Forces the LLM to output a single JSON object containing the answer text
    and a list of all sources that were used to construct it.
    """
    answer: str = Field(
        description="Final answer text with inline citations in the form [1], [2]…"
    )
    sources: List[SourceInfo] = Field(
        default_factory=list,
        description="List of source objects that the answer refers to."
    )


class RelevanceVerdict(BaseModel):
    """
    Data contract for the RelevanceJudge agent.
    Evaluates whether retrieved chunks answer the question and optionally
    suggests a better search query.
    """
    score: int = Field(
        ge=1, le=5, description="Relevance score from 1 (irrelevant) to 5 (perfect match)."
    )
    reasoning: str = Field(
        description="Brief explanation of why the score was assigned."
    )
    suggested_query: Optional[str] = Field(
        default=None,
        description="A rewritten search query if the current results are insufficient.",
    )


class SubQuery(BaseModel):
    """
    A single sub‑question derived from a complex user query.
    """
    text: str = Field(
        description="The sub‑question text, ready for search."
    )
    reason: str = Field(
        description="Why this sub‑question is needed."
    )


class DecomposedQuery(BaseModel):
    """
    Result of query decomposition.
    For simple questions, sub_queries will contain only the original query.
    """
    is_complex: bool = Field(
        description="True if the question needed decomposition."
    )
    sub_queries: List[SubQuery] = Field(
        description="List of sub‑questions (at least one)."
    )


class UnsupportedClaim(BaseModel):
    """A claim from the answer that lacks support in the retrieved chunks."""
    claim: str = Field(
        description="The unsupported statement from the answer."
    )
    reason: str = Field(
        description="Why it could not be verified against the chunks."
    )


class FaithfulnessReport(BaseModel):
    """Result of the faithfulness check."""
    is_faithful: bool = Field(description="True if every claim is supported by the chunks.")
    unsupported_claims: List[UnsupportedClaim] = Field(
        default_factory=list,
        description="Claims that could not be verified.",
    )
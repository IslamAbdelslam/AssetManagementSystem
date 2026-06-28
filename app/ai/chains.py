"""
LangChain LCEL chains for Gemini-powered asset analysis.

Security contract:
  - LLM output is ALWAYS validated by Pydantic before any DB operation.
  - The LLM never generates asset records — it only produces filter parameters.
  - Hallucinated asset values cannot appear in responses (all data comes from DB).
"""
from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import ValidationError

from app.ai.prompts import NL_QUERY_SYSTEM_PROMPT, SUMMARIZE_SYSTEM_PROMPT
from app.ai.schemas import AssetFilterSchema
from app.config import get_settings
from app.core.exceptions import ValidationError as AppValidationError
from app.core.logging import get_logger

log = get_logger(__name__)
settings = get_settings()


def _get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.0,        # Deterministic — no creative hallucination
        max_output_tokens=1024,
    )


async def run_nl_query_chain(nl_query: str) -> AssetFilterSchema:
    """
    Translates a natural language query into a validated AssetFilterSchema.
    Raises AppValidationError if LLM output cannot be parsed.
    """
    llm = _get_llm()

    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=NL_QUERY_SYSTEM_PROMPT),
        ("human", "{query}"),
    ])

    chain = prompt | llm | JsonOutputParser()

    try:
        raw_output = await chain.ainvoke({"query": nl_query})
        log.info("ai.nl_query.raw_output", query=nl_query[:100])
    except Exception as exc:
        log.error("ai.nl_query.llm_error", error=str(exc))
        raise AppValidationError("AI service is temporarily unavailable. Please try again.")

    # Pydantic validation — hallucination guard
    try:
        return AssetFilterSchema(**raw_output)
    except (ValidationError, TypeError) as exc:
        log.warning("ai.nl_query.parse_failed", error=str(exc), output=str(raw_output)[:200])
        raise AppValidationError(
            "Could not parse your query. Please rephrase it more specifically."
        )


async def run_summarize_chain(asset_data: str, focus: str | None) -> str:
    """
    Generates a natural language summary of the asset landscape.
    Input: pre-fetched asset data as JSON string (grounded — no hallucination possible).
    """
    llm = _get_llm()

    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=SUMMARIZE_SYSTEM_PROMPT),
        ("human", "Focus: {focus}\n\nAsset Data:\n{asset_data}"),
    ])

    chain = prompt | llm

    try:
        result = await chain.ainvoke({
            "focus": focus or "general overview",
            "asset_data": asset_data,
        })
        return result.content  # type: ignore[union-attr]
    except Exception as exc:
        log.error("ai.summarize.llm_error", error=str(exc))
        raise AppValidationError("Summary generation failed. Please try again.")

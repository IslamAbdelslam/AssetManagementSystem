"""AI Pydantic schemas for NL query and summary endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NLQueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500, description="Natural language question about your assets")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"query": "Show me all expired certificates on production subdomains"},
                {"query": "Which IP addresses have open port 22?"},
                {"query": "List all stale domains discovered from scans"},
            ]
        }
    }


class AssetFilterSchema(BaseModel):
    """Structured filter extracted from NL query by the LLM. Validated before DB use."""
    type: str | None = None
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    value_contains: str | None = None
    source: str | None = None
    metadata_filter: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value pairs to match inside metadata JSON",
    )
    explanation: str = Field(default="", description="LLM explanation of how it interpreted the query")


class NLQueryResponse(BaseModel):
    query: str
    interpretation: str
    filter_applied: dict[str, Any]
    total_results: int
    results: list[dict[str, Any]]


class SummarizeRequest(BaseModel):
    focus: str | None = Field(
        None,
        max_length=200,
        description="Optional focus area e.g. 'certificates', 'stale assets'",
    )


class SummarizeResponse(BaseModel):
    focus: str | None
    summary: str
    asset_counts: dict[str, int]

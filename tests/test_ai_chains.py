"""Tests for AI chains mocking the actual LLM ainvoke method."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.ai.chains import run_nl_query_chain, run_summarize_chain
from app.core.exceptions import ValidationError as AppValidationError

pytestmark = pytest.mark.asyncio


def fake_llm_json(*args, **kwargs):
    return AIMessage(content='{"type": "domain", "status": "active", "tags": ["prod"], "value_contains": null, "source": null, "metadata_filter": {}, "explanation": "Test explanation"}')

@patch("app.ai.chains._get_llm", return_value=RunnableLambda(fake_llm_json))
async def test_run_nl_query_chain_success(mock_get_llm):
    result = await run_nl_query_chain("show me prod domains")
    assert result.type == "domain"
    assert result.status == "active"
    assert "prod" in result.tags
    assert result.explanation == "Test explanation"


def fake_llm_malformed(*args, **kwargs):
    return AIMessage(content='{"type": 123, "unknown_field": true}')

@patch("app.ai.chains._get_llm", return_value=RunnableLambda(fake_llm_malformed))
async def test_run_nl_query_chain_hallucination_guard(mock_get_llm):
    with pytest.raises(AppValidationError) as exc_info:
        await run_nl_query_chain("malformed request")
    assert "Could not parse your query" in str(exc_info.value)


def fake_llm_summary(*args, **kwargs):
    return AIMessage(content="This is a great security summary.")

@patch("app.ai.chains._get_llm", return_value=RunnableLambda(fake_llm_summary))
async def test_run_summarize_chain_success(mock_get_llm):
    asset_data = json.dumps([{"type": "domain", "value": "test.com"}])
    result = await run_summarize_chain(asset_data, "domains")
    assert result == "This is a great security summary."

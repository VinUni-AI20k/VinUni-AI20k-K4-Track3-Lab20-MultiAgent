"""Unit tests for services.search_client.SearchClient.

Uses a tiny 2-topic fixture corpus (not the real 30-file
ai_agent_offline_research_corpus_v2/) so these tests are fast, deterministic,
and don't depend on that directory's exact content.
"""

import json
from pathlib import Path

import pytest

from multi_agent_research_lab.core.errors import AgentExecutionError
from multi_agent_research_lab.services.search_client import SearchClient


def _write_topic(
    directory: Path, filename: str, topic_name: str, article_title: str, article_content: str
) -> None:
    topic = {
        "topic": {"name": topic_name},
        "knowledge_base": {
            "knowledge_articles": [
                {"article_id": "A01", "title": article_title, "content": article_content}
            ],
            "source_documents": [
                {
                    "document_id": "SRC01",
                    "title": f"{topic_name} source",
                    "full_text": article_content,
                    "is_synthetic": False,
                    "provenance_url": "https://example.com/src01",
                }
            ],
        },
    }
    (directory / filename).write_text(json.dumps(topic), encoding="utf-8")


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    _write_topic(
        tmp_path,
        "01_multi_agent.json",
        "Multi-Agent Coordination",
        "Coordination overhead",
        "Coordination overhead in multi-agent systems arises from task decomposition and handoffs.",
    )
    _write_topic(
        tmp_path,
        "02_cooking.json",
        "Cooking",
        "Pasta recipes",
        "This article is about cooking pasta and choosing the right tomato sauce.",
    )
    return tmp_path


def test_loads_both_knowledge_articles_and_source_documents(corpus_dir: Path) -> None:
    client = SearchClient(corpus_dir=corpus_dir)
    results = client.search("multi-agent coordination overhead handoffs", max_results=4)
    kinds = {r.metadata["kind"] for r in results}
    assert kinds == {"knowledge_article", "source_document"}


def test_ranks_relevant_topic_above_unrelated_topic(corpus_dir: Path) -> None:
    client = SearchClient(corpus_dir=corpus_dir)
    results = client.search("multi-agent coordination overhead handoffs", max_results=4)

    coordination_scores = [r.metadata["match_score"] for r in results if "Multi-Agent" in r.title]
    cooking_scores = [r.metadata["match_score"] for r in results if "Cooking" in r.title]

    assert min(coordination_scores) > max(cooking_scores)


def test_match_score_does_not_leak_between_queries(corpus_dir: Path) -> None:
    """Regression test for a real bug found while implementing this client:
    search() must return a *copy* of each cached document annotated with
    match_score, not mutate the module-level cached corpus in place. Otherwise
    an unrelated query run in between would overwrite the score for a
    previously (and later re-) searched document. See
    docs/solution_walkthrough.md section 7.
    """

    client = SearchClient(corpus_dir=corpus_dir)
    first = client.search("multi-agent coordination overhead", max_results=1)[0]
    client.search("completely unrelated gibberish about spacecraft", max_results=1)
    third = client.search("multi-agent coordination overhead", max_results=1)[0]

    assert first.metadata["match_score"] == third.metadata["match_score"]


def test_missing_corpus_dir_raises_agent_execution_error(tmp_path: Path) -> None:
    with pytest.raises(AgentExecutionError):
        SearchClient(corpus_dir=tmp_path / "does-not-exist")


def test_search_returns_best_effort_results_when_no_keyword_matches(corpus_dir: Path) -> None:
    client = SearchClient(corpus_dir=corpus_dir)
    results = client.search("zzz nonexistent query terms qqq", max_results=2)

    assert len(results) == 2
    assert all(r.metadata["match_score"] == 0 for r in results)


def test_search_handles_a_query_that_tokenizes_to_no_terms(corpus_dir: Path) -> None:
    # "the a an" is entirely stopwords/too-short tokens -> _tokenize(query) == []
    # (a separate code path from "terms present but none matched").
    client = SearchClient(corpus_dir=corpus_dir)
    results = client.search("the a an", max_results=2)

    assert len(results) == 2
    assert all(r.metadata["match_score"] == 0 for r in results)

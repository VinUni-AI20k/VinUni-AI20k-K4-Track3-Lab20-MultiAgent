"""Search client abstraction for ResearcherAgent."""

import json
import logging
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from multi_agent_research_lab.core.errors import AgentExecutionError
from multi_agent_research_lab.core.schemas import SourceDocument

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")
# Short/common words are excluded so scoring reflects topical overlap, not
# incidental substring hits (e.g. "in" inside "coordination").
_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "for", "to", "and", "or", "is", "are",
    "with", "that", "this", "by", "as", "be", "it", "at", "from", "not",
}  # fmt: skip


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if len(w) > 2 and w not in _STOPWORDS]


# src/multi_agent_research_lab/services/search_client.py -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CORPUS_DIR = _REPO_ROOT / "ai_agent_offline_research_corpus_v2" / "topics"


class SearchClient:
    """Offline search client backed by the local research corpus.

    Provider-agnostic: this is one implementation of the `search()` contract. A
    live-web variant (Tavily, Bing, SerpAPI) can be dropped in later behind the
    same interface without touching `ResearcherAgent`.
    """

    def __init__(self, corpus_dir: Path | None = None) -> None:
        self._corpus_dir = corpus_dir or _DEFAULT_CORPUS_DIR
        self._documents = _load_corpus(self._corpus_dir)

    def search(self, query: str, max_results: int = 5) -> list[SourceDocument]:
        """Rank corpus documents by keyword overlap with the query.

        Always returns up to `max_results` documents (best-effort) rather than an
        empty list, so a single unmatched query does not stall the workflow. Each
        result carries a `match_score` in its metadata so downstream agents (or a
        human reviewer) can tell a strong match from a weak best-effort guess.
        """

        terms = _tokenize(query)
        scored = sorted(
            ((_score(doc, terms), doc) for doc in self._documents),
            key=lambda pair: pair[0],
            reverse=True,
        )
        top = scored[:max_results]

        if top and top[0][0] == 0:
            logger.warning(
                "search_client.no_keyword_match query=%r - returning corpus head as best effort",
                query,
            )

        return [
            doc.model_copy(update={"metadata": {**doc.metadata, "match_score": score}})
            for score, doc in top
        ]


def _score(doc: SourceDocument, terms: list[str]) -> int:
    if not terms:
        return 0
    haystack_counts = Counter(_tokenize(f"{doc.title} {doc.snippet}"))
    return sum(haystack_counts[term] for term in terms)


@lru_cache(maxsize=8)
def _load_corpus(corpus_dir: Path) -> tuple[SourceDocument, ...]:
    """Load and flatten every topic file in `corpus_dir` into SourceDocuments.

    Cached (same pattern as `core.config.get_settings`) because the corpus is
    read-only and re-parsing ~30 JSON files on every `SearchClient()` call would
    otherwise cost real latency inside a benchmark loop that runs many queries.
    """

    if not corpus_dir.is_dir():
        raise AgentExecutionError(
            f"Offline research corpus not found at {corpus_dir}. Clone the lab repo with "
            "ai_agent_offline_research_corpus_v2/ included, or pass an explicit corpus_dir."
        )

    documents: list[SourceDocument] = []
    topic_files = sorted(corpus_dir.glob("*.json"))
    for topic_file in topic_files:
        data: dict[str, Any] = json.loads(topic_file.read_text(encoding="utf-8"))
        knowledge_base = data["knowledge_base"]
        topic_name = data["topic"]["name"]

        for article in knowledge_base["knowledge_articles"]:
            documents.append(
                SourceDocument(
                    title=f"{topic_name} - {article['title']}",
                    url=None,
                    snippet=article["content"][:500],
                    metadata={
                        "kind": "knowledge_article",
                        "article_id": article["article_id"],
                        "topic_file": topic_file.name,
                        "is_synthetic": False,
                    },
                )
            )

        for source in knowledge_base["source_documents"]:
            documents.append(
                SourceDocument(
                    title=source["title"],
                    url=source.get("provenance_url"),
                    snippet=source["full_text"][:500],
                    metadata={
                        "kind": "source_document",
                        "source_id": source["document_id"],
                        "topic_file": topic_file.name,
                        "is_synthetic": source["is_synthetic"],
                    },
                )
            )

    logger.info(
        "search_client.loaded documents=%d topics=%d corpus_dir=%s",
        len(documents),
        len(topic_files),
        corpus_dir,
    )
    return tuple(documents)

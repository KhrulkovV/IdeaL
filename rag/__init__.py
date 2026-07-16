"""IdeaL GraphRAG — optional, read-side semantic retrieval over the idea store.

Additive: never writes to the store, requires no server changes. Pulls the whole store via the
existing ``ideal.py export --format json`` client and retrieves with LangChain's first-party
``langchain-graph-retriever`` (``GraphRetriever``): vector similarity seeds, then traversal of the
``[[target-id]]`` wikilinks pulls in the ego-network — including ideas whose own text didn't match,
because the edges are Claude-reasoned. A thin LangGraph ``StateGraph`` wraps it (retrieve → format,
no LLM). See ``docs/superpowers/specs/2026-07-16-graphrag-retrieval-design.md``.
"""

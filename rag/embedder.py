"""The default embedder: sentence-transformers all-MiniLM-L6-v2 as a LangChain ``Embeddings``.

Implements the ``langchain_core.embeddings.Embeddings`` interface so it drops straight into
``InMemoryVectorStore``. torch/sentence-transformers are imported lazily on construction, so the
module imports cheaply and tests can substitute a fake ``Embeddings`` without pulling torch.
"""
from __future__ import annotations

import os

from langchain_core.embeddings import Embeddings

DEFAULT_MODEL = os.environ.get("IDEAL_RAG_MODEL", "all-MiniLM-L6-v2")


class MiniLMEmbeddings(Embeddings):
    """Local semantic embedder. L2-normalized vectors (cosine == dot product)."""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        from sentence_transformers import SentenceTransformer  # lazy: heavy import

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def _encode(self, texts):
        vecs = self._model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        return [v.tolist() for v in vecs]

    def embed_documents(self, texts):
        return self._encode(texts) if texts else []

    def embed_query(self, text):
        return self._encode([text])[0]

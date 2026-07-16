"""Pydantic request/response models. Validation lives here."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

EdgeType = Literal["similar", "connected"]


class EdgeIn(BaseModel):
    target_id: str = Field(min_length=1)
    type: EdgeType
    note: str = ""


class IdeaCreate(BaseModel):
    title: str
    body: str
    author: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    task: Optional[str] = None
    usefulness: Optional[int] = Field(default=None, ge=0, le=100)
    reputation: Optional[int] = Field(default=None, ge=0, le=100)
    status: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    edges: List[EdgeIn] = Field(default_factory=list)

    @field_validator("title", "body")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class IdeaUpdate(BaseModel):
    """Partial update. Only fields present in the request body are changed;
    an explicit ``null`` clears a nullable field, while an omitted key is left
    untouched (the endpoint relies on ``model_dump(exclude_unset=True)``)."""
    title: Optional[str] = None
    body: Optional[str] = None
    author: Optional[str] = None
    tags: Optional[List[str]] = None
    task: Optional[str] = None
    usefulness: Optional[int] = Field(default=None, ge=0, le=100)
    reputation: Optional[int] = Field(default=None, ge=0, le=100)
    status: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None

    @field_validator("title", "body")
    @classmethod
    def _non_empty(cls, v: Optional[str]) -> str:
        # Runs only when the field is provided; title/body are NOT NULL, so a
        # provided null or blank is rejected rather than written.
        if v is None or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class LinkCreate(BaseModel):
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    type: EdgeType
    note: str = ""


class LinkDelete(BaseModel):
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    type: EdgeType


class IdeaCreated(BaseModel):
    id: str
    edges_created: int
    edges_ignored: List[str] = Field(default_factory=list)


# --- semantic search (optional server-side RAG) ------------------------------

class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=8, ge=1, le=100)        # max ideas returned
    start_k: int = Field(default=4, ge=1, le=100)  # vector-similarity seeds
    hops: int = Field(default=1, ge=0, le=5)       # link-traversal depth (0 = pure vector)

    @field_validator("query")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class SearchHit(BaseModel):
    id: str
    title: str
    depth: int                       # 0 = vector seed, >=1 = reached via that many link hops
    score: Optional[float] = None    # cosine similarity for seeds; null for reached ideas
    reason: str                      # human-readable provenance
    tags: List[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    results: List[SearchHit]
    context: str                     # ready-to-read markdown block of the retrieved ideas

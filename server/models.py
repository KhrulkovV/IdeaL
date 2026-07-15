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
    usefulness: Optional[int] = None
    reputation: Optional[int] = None
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
    usefulness: Optional[int] = None
    reputation: Optional[int] = None
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

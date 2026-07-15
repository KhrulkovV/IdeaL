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


class LinkCreate(BaseModel):
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    type: EdgeType
    note: str = ""


class IdeaCreated(BaseModel):
    id: str
    edges_created: int
    edges_ignored: List[str] = Field(default_factory=list)

from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    url: str
    title: str
    snippet: str

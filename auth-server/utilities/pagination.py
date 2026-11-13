"""One shape for every paged list: `{items, total}` with `?limit=&offset=`.

Every caller must order the queryset on a unique key, otherwise rows can repeat or vanish between pages.
"""

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from tortoise.queryset import QuerySet

T = TypeVar("T")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


class PageParams:
    """FastAPI dependency: `?limit=50&offset=0`."""

    def __init__(
        self,
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Rows per page"),
        offset: int = Query(0, ge=0, description="Rows to skip"),
    ):
        self.limit = limit
        self.offset = offset


async def paginate(qs: QuerySet, params: PageParams) -> dict:
    """Count the filtered queryset and fetch one page. Returns a dict the router's Page model validates."""
    return {"items": await qs.limit(params.limit).offset(params.offset), "total": await qs.count()}

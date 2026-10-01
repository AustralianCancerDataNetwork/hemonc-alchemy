"""Shared execution and literal-search behaviour for projected statements."""

from enum import Enum

from sqlalchemy import String, cast, func, or_, select

from .read_models import Page
from .specs import Pagination


def search_predicate(label, identity, query):
    return or_(label.icontains(query, autoescape=True), cast(identity, String) == query)


def paginate(session, statement, pagination: Pagination, record_type):
    total = session.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    rows = session.execute(
        statement.offset((pagination.page - 1) * pagination.page_size).limit(
            pagination.page_size
        )
    ).mappings()
    records = tuple(
        record_type(
            **{
                key: value.value if isinstance(value, Enum) else value
                for key, value in row.items()
            }
        )
        for row in rows
    )
    return Page(records, total, pagination.page, pagination.page_size)

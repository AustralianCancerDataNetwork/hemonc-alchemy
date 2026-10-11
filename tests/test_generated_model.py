"""Smoke test for the currently committed generated model.

Confirms model/entities.py isn't just syntactically valid (that's
compiler/validate.py's job) but actually *works* as SQLAlchemy: every class
imports, every relationship (declarative and soft/inferred) resolves to a
real class, and the resulting schema is valid, creatable SQL. This is a
materially higher bar than "the file parses" -- two real bugs were only
caught by actually running this exact check against the real regenerated
output (a missing `datetime` import, and a genuine HemOnc column literally
named `relationship` shadowing the imported `relationship()` function
within its own class body).

Skipped if entities.py is still the empty placeholder (no `regen` has been
run yet in this checkout).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as so

from hemonc_alchemy.model import entities
from hemonc_alchemy.model.base import Base, concrete_entities

pytestmark = pytest.mark.skipif(
    not concrete_entities(entities),
    reason="model/entities.py has no generated classes yet -- run `hemonc-alchemy regen` first",
)


def test_generated_classes_import_and_configure():
    entity_classes = concrete_entities(entities)
    assert len(entity_classes) > 0

    # Every declarative and soft/inferred relationship must resolve to a
    # real class -- this is where a dangling `relationship(...)` target or
    # a shadowed builtin/import name would surface.
    so.configure_mappers()


def test_generated_schema_creates_in_sqlite():
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert len(Base.metadata.tables) > 0


def test_catalogue_lookup_indexes_are_created():
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = sa.inspect(engine)
    indexes = {
        (table, index["name"], tuple(index["column_names"]))
        for table in ("variants_study", "sigs")
        for index in inspector.get_indexes(table)
    }
    assert ("variants_study", "ix_variants_study_study", ("study",)) in indexes
    assert ("sigs", "ix_sigs_variant_cui", ("variant_cui",)) in indexes

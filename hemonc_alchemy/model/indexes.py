"""Hand-written indexes on the columns the catalogue joins and filters by.

HemOnc's tables are linked by shared values rather than declared foreign keys,
so the generated model indexes only primary keys and natural keys.
"""

from __future__ import annotations

import sqlalchemy as sa

from .entities import Sigs, variants_StudyMap

# Map rows are matched to studies by name; the primary key leads with parent_id.
sa.Index("ix_variants_study_study", variants_StudyMap.__table__.c.study)

# Dosing instructions are looked up and counted per variant.
sa.Index("ix_sigs_variant_cui", Sigs.__table__.c.variant_cui)

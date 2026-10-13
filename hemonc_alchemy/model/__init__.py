"""The HemOnc entity classes.

Every entity generated from the data dictionary is importable from here. The
list is declared by the generated module itself, so a table added in a HemOnc
release becomes importable as soon as the model is regenerated.
"""

from .base import Base, EntityBase
from .entities import *
from .entities import __all__ as _entity_names

# Names come from the generated module, so they are strings at runtime
# even though a checker can't see inside the list.
__all__ = ["Base", "EntityBase", *_entity_names]  # noqa: PLE0604

# Must stay below the imports above, and separate from them so an import
# sorter can't move it: relationships are assigned onto the entity classes,
# which have to exist first. Importing `hemonc_alchemy.model` is what puts
# them there -- importing `hemonc_alchemy.model.entities` directly does not.
from . import indexes, relationships  # noqa: F401

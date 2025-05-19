from enum import Enum

from pydantic import Field

from genie_flow.model.versioned import VersionedModel


class PersistenceLevel(Enum):
    EPHEMERAL = 0
    LONG_TERM_PERSISTENCE = 1


class Persistence(VersionedModel):
    level: PersistenceLevel = Field(
        description="the persistence level of the object"
    )

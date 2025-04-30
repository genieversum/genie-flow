import re

from pydantic import BaseModel, Field, AfterValidator, computed_field, ConfigDict
from typing import Optional, Annotated

from genie_flow.model.versioned import VersionedModel


def is_printable(value: str) -> str:
    if not value.isprintable():
        raise ValueError(f"{value} contains characters that are not printable")
    return value

def is_email(value: str) -> str:
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', value):
        raise ValueError(f"{value} is not a valid email address")
    return value
    
Printable = Annotated[str, AfterValidator(is_printable)]

class User(VersionedModel):
    
    email: Annotated[str, AfterValidator(is_email)] = Field(
        description="the email address of the current user"
    )
    firstname: Printable = Field(
        description="the first name of the current user"
    )
    lastname: Printable = Field(
        description="the last name of the current user"
    )
    custom_properties: Optional[dict[Printable,Printable]] = Field(
        default=None,
        description="dict of custom properties specific to the agent"
    )

    @computed_field
    @property
    def name(self) -> str:
        return f"{self.firstname} {self.lastname}"
    
    model_config = ConfigDict(
        json_schema_extra={"schema_version": 0}
    )

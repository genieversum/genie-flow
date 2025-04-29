import re

from pydantic import BaseModel, Field, AfterValidator, computed_field
from typing import Optional, Annotated


def is_printable(value: str) -> str:
    if not value.isprintable():
        raise ValueError(f"{value} contains characters that are not printable")
    return value

def is_email(value: str) -> str:
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', value):
        raise ValueError(f"{value} is not a valid email address")
    return value
    
Printable = Annotated[str, AfterValidator(is_printable)]

class User(BaseModel):
    
    email: Annotated[str, AfterValidator(is_email)] = Field(
        description="the email address of the current user"
    )
    firstname: Printable = Field(
        description="the first name of the current user"
    )
    lastname: Printable = Field(
        description="the last name of the current user"
    )
    picture: Optional[bytes] = Field(
        default=None,
        description="the profile picture of the current user"
    )
    job_title: Optional[Printable] = Field(
        default=None,
        description="the job tite of the current user"
    )
    department: Optional[Printable] = Field(
        default=None,
        description="the department of the current user"
    )
    gtm: Optional[Printable] = Field(
        default=None,
        description="the GTM of the current user"
    )
    location: Optional[Printable] = Field(
        default=None,
        description="the base location of the current user"
    )

    @computed_field
    @property
    def name(self) -> str:
        return f"{self.firstname} {self.lastname}"
    


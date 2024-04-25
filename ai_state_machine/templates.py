from os import PathLike
from typing import Optional, List

from jinja2 import Environment, FileSystemLoader, PrefixLoader, BaseLoader

_ENVIRONMENT: Optional[Environment] = None
_TEMPLATE_DIRECTORIES: dict[str, BaseLoader] = dict()


def get_environment() -> Environment:
    global _ENVIRONMENT
    global _TEMPLATE_DIRECTORIES

    if _ENVIRONMENT is None:
        _ENVIRONMENT = Environment(loader=PrefixLoader(_TEMPLATE_DIRECTORIES))
    return _ENVIRONMENT


def register_template_directory(prefix: str, directory: str | PathLike):
    global _TEMPLATE_DIRECTORIES
    _TEMPLATE_DIRECTORIES[prefix] = FileSystemLoader(directory)

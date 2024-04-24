from typing import Optional, List

from jinja2 import Environment, FileSystemLoader, ChoiceLoader, PrefixLoader

_ENVIRONMENT: Optional[Environment] = None
_TEMPLATE_DIRECTORIES: dict[str, str] = dict()


def get_environment() -> Environment:
    global _ENVIRONMENT
    global _TEMPLATE_DIRECTORIES

    if _ENVIRONMENT is None:
        _ENVIRONMENT = Environment(
            loader=PrefixLoader(
                {
                    k: FileSystemLoader(v)
                    for k, v in _TEMPLATE_DIRECTORIES.items()
                }
            )
        )
    return _ENVIRONMENT


def register_template_directory(prefix: str, director: str):
    global _TEMPLATE_DIRECTORIES
    _TEMPLATE_DIRECTORIES[prefix] = director

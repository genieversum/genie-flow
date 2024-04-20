from ai_state_machine.genie_state_machine import GenieModel
from ai_state_machine.store import get_fully_qualified_name_from_class, \
    get_class_from_fully_qualified_name

_REGISTRY: dict[str, type[GenieModel]] = dict()


def register(model_key: str, cls: type[GenieModel]):
    assert isinstance(model_key, str)
    assert issubclass(cls, GenieModel)

    _REGISTRY[model_key] = cls  # get_fully_qualified_name_from_class(cls)


def retrieve(model_key: str) -> type[GenieModel]:
    assert isinstance(model_key, str)

    return _REGISTRY[model_key]  # get_class_from_fully_qualified_name(_REGISTRY[model_key])

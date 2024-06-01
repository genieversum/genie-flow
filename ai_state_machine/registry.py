from ai_state_machine.genie_model import GenieModel

ModelKeyRegistryType = dict[str, type[GenieModel]]
_REGISTRY: dict[str, type[GenieModel]] = dict()


# def register(model_key: str, cls: type[GenieModel]):
#     assert isinstance(model_key, str)
#     assert issubclass(cls, GenieModel)
#
#     _REGISTRY[model_key] = cls
#
#
# def retrieve(model_key: str) -> type[GenieModel]:
#     assert isinstance(model_key, str)
#
#     return _REGISTRY[model_key]

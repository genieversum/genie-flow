from typing import Type

from ai_state_machine.invoker.genie import GenieInvoker
from ai_state_machine.invoker.openai import AzureOpenAIChatInvoker, AzureOpenAIChatJSONInvoker
from ai_state_machine.invoker.verbatim import VerbatimInvoker

_REGISTRY: dict[str, Type[GenieInvoker]] = dict(
    verbatim=VerbatimInvoker,
    azure_openai_chat=AzureOpenAIChatInvoker,
    azure_openai_chat_json=AzureOpenAIChatJSONInvoker,
)


def create_genie_invoker(invoker_config: dict[str]) -> GenieInvoker:
    cls = _REGISTRY[invoker_config["type"]]
    return cls.from_config(invoker_config)


def register_invoker(invoker_name: str, invoker_class: Type[GenieInvoker]):
    """
    Register your own invoker. It then becomes
    """
    if invoker_name in _REGISTRY:
        raise ValueError(f"'{invoker_name}' is already registered")
    _REGISTRY[invoker_name] = invoker_class

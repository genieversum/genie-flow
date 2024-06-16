from typing import Type

from ai_state_machine.invoker.genie import GenieInvoker
from ai_state_machine.invoker.openai import (
    AzureOpenAIChatInvoker,
    AzureOpenAIChatJSONInvoker,
)
from ai_state_machine.invoker.verbatim import VerbatimInvoker

_REGISTRY: dict[str, Type[GenieInvoker]] = dict(
    verbatim=VerbatimInvoker,
    azure_openai_chat=AzureOpenAIChatInvoker,
    azure_openai_chat_json=AzureOpenAIChatJSONInvoker,
)


def create_genie_invoker(invoker_config: dict[str]) -> GenieInvoker:
    cls = _REGISTRY[invoker_config["type"]]
    return cls.from_config(invoker_config)


class InvokerFactory:

    def __init__(self, config: dict):
        self.config = config
        self._registry: dict[str, Type[GenieInvoker]] = dict()

    def register_invoker(self, invoker_name: str, invoker_class: Type[GenieInvoker]):
        """
        Register your own invoker. It then becomes usable in any `meta.yaml` directive in a
        template directory.

        :param invoker_name: The name of the invoker, as it will appear in the `meta.yaml`
        :param invoker_class: The invoker class to register.
        """
        if invoker_name in self._registry:
            raise ValueError(f"'{invoker_name}' is already registered")
        self._registry[invoker_name] = invoker_class

    def create_invoker(self, invoker_config: dict) -> GenieInvoker:
        """
        Create a new invoker, as specified by `invoker_config`. Uses the application's
        configuration as a base. Any configuration specified in `invoker_config` takes
        precedence over any other configuration specified in the application's configuration.

        :param invoker_config: The invoker config to create.
        :return: The created invoker.
        :raises ValueError: If the invoker is not registered or the invoker is invalid.
        """
        try:
            invoker_type = invoker_config["type"]
        except KeyError:
            raise ValueError(f"Invalid invoker config: {invoker_config}")

        try:
            cls = self._registry[invoker_type]
        except KeyError:
            raise ValueError(f"Unknown invoker type: {invoker_type}")

        config = self.config[invoker_type] if invoker_type in self.config.keys() else dict()
        config.update(invoker_config)
        return cls.from_config(config)

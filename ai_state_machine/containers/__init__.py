from os import PathLike
from typing import Optional

from ai_state_machine.containers.core import GenieFlowCoreContainer
from ai_state_machine.containers.genieflow import GenieFlowContainer
from ai_state_machine.containers.persistence import GenieFlowPersistenceContainer
from ai_state_machine.environment import GenieEnvironment


_CONTAINER_APP: Optional[GenieFlowContainer] = None


def init_genie_flow(config_file_path: str | PathLike) -> GenieFlowContainer:
    global _CONTAINER_APP

    if _CONTAINER_APP is not None:
        raise RuntimeError("Already initialized")

    # create and wire the container
    _CONTAINER_APP = GenieFlowContainer()
    _CONTAINER_APP.config.from_yaml(config_file_path, required=True)
    _CONTAINER_APP.wire(packages=["ai_state_machine"])
    _CONTAINER_APP.init_resources()

    return _CONTAINER_APP


def get_environment() -> GenieEnvironment:
    global _CONTAINER_APP

    if _CONTAINER_APP is None:
        raise RuntimeError("Not initialized")

    return _CONTAINER_APP.genie_environment()

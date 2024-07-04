from os import PathLike

from celery import Celery
from fastapi import FastAPI

from ai_state_machine.containers.genieflow import GenieFlowContainer
from ai_state_machine.environment import GenieEnvironment


class GenieFlow:

    def __init__(self, container: GenieFlowContainer):
        self.container = container

    @classmethod
    def from_yaml(cls, config_file_path: str | PathLike) -> "GenieFlow":
        container = GenieFlowContainer()
        container.config.from_yaml(config_file_path, required=True)
        container.wire(packages=["ai_state_machine"])
        container.storage.container.wire(modules=["ai_state_machine.celery"])
        container.init_resources()

        return cls(container)

    @property
    def genie_environment(self) -> GenieEnvironment:
        return self.container.genie_environment()

    @property
    def fastapi_app(self) -> FastAPI:
        return self.container.fastapi_app()

    @property
    def celery_app(self) -> Celery:
        return self.container.celery_app()

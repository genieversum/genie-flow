from os import PathLike

from celery import Celery
from fastapi import FastAPI

from genie_flow.containers.genieflow import GenieFlowContainer
from genie_flow.environment import GenieEnvironment


class GenieFlow:

    def __init__(self, container: GenieFlowContainer):
        self.container = container

    @classmethod
    def from_yaml(cls, config_file_path: str | PathLike) -> "GenieFlow":
        container = GenieFlowContainer()
        container.config.from_yaml(config_file_path, required=True)
        container.wire(packages=["genie_flow"])
        container.storage.container.wire(packages=["genie_flow.celery"])
        container.permanent_storage.container.wire(packages=["genie_flow.mongo"])
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

from os import PathLike
from pathlib import Path
from typing import TypedDict, Callable, Optional, TypeVar, Any, Type, Union

import jinja2
from loguru import logger
import yaml
from celery import Task
from jinja2 import Environment, PrefixLoader, TemplateNotFound
from pydantic import BaseModel
from statemachine import State

from genie_flow.genie import GenieModel, GenieStateMachine
from genie_flow_invoker.pool import InvokersPool
from genie_flow_invoker.factory import InvokerFactory
from genie_flow.model.types import ModelKeyRegistryType
from genie_flow.model.template import CompositeTemplateType, MapTaskTemplate, NamedQueueTaskTemplate

_META_FILENAME: str = "meta.yaml"
_T = TypeVar("_T")


class _RegisteredDirectory(TypedDict):
    directory: Path
    jinja_loader: jinja2.FileSystemLoader
    config: dict
    invokers: Optional[InvokersPool]


class GenieEnvironment:
    """
    The `GenieEnvironment` deals with maintaining the templates registry, rendering templates
    and invoking `Invoker`s with a data context and a dialogue.
    """

    def __init__(
        self,
        template_root_path: str | PathLike,
        pool_size: int,
        model_key_registry: ModelKeyRegistryType,
        invoker_factory: InvokerFactory,
    ):
        self.template_root_path = Path(template_root_path).resolve()
        self.pool_size = pool_size
        self.model_key_registry = model_key_registry
        self.invoker_factory = invoker_factory

        self._jinja_env: Optional[Environment] = None
        self._template_directories: dict[str, _RegisteredDirectory] = {}

    def _walk_directory_tree_upward(
        self, start_directory: Path, execute: Callable[[Path, Optional[dict]], _T]
    ) -> _T:
        start_directory = start_directory.resolve()
        if start_directory == self.template_root_path:
            return execute(start_directory, None)

        parent_directory = start_directory.parent
        if parent_directory == start_directory:  # we reached the top-most directory
            raise ValueError("start_directory not part of the template directory tree")

        parent_result = self._walk_directory_tree_upward(parent_directory, execute)
        return execute(start_directory, parent_result)

    def _add_all_directories(self, start_directory: Path):
        start_directory = start_directory.resolve()
        for directory_element in start_directory.glob("*"):
            if directory_element.is_dir():
                self._add_all_directories(directory_element)
        self.register_template_directory(start_directory.name, start_directory)

    @staticmethod
    def read_meta(directory: Path, parent_config: Optional[dict]) -> dict:
        if parent_config is None:
            parent_config = {}
        try:
            with open(directory / _META_FILENAME, "r") as meta_file:
                meta = yaml.safe_load(meta_file)
                parent_config.update(meta)
                return parent_config
        except FileNotFoundError:
            logger.debug(f"No meta file found in {directory}")
            return parent_config

    @property
    def jinja_loader_mapping(self) -> dict[str, jinja2.BaseLoader]:
        return {
            prefix: directory["jinja_loader"]
            for prefix, directory in self._template_directories.items()
        }

    @property
    def jinja_env(self) -> jinja2.Environment:
        if self._jinja_env is None:
            self._jinja_env = Environment(
                loader=PrefixLoader(self.jinja_loader_mapping)
            )
        return self._jinja_env

    def _non_existing_templates(self, template: CompositeTemplateType) -> list[CompositeTemplateType]:
        if isinstance(template, str):
            try:
                _ = self.get_template(template)
                return []
            except TemplateNotFound:
                return [template]

        if isinstance(template, Task):
            # TODO might want to check if the task exists
            return []

        if isinstance(template, list):
            result = []
            for t in template:
                result.extend(self._non_existing_templates(t))
            return result

        if isinstance(template, dict):
            result = []
            for key in template.keys():
                result.extend(
                    [f"{key}:{t}" for t in self._non_existing_templates(template[key])]
                )
            return result

        if isinstance(template, MapTaskTemplate):
            return self._non_existing_templates(template.template_name)

        if isinstance(template, NamedQueueTaskTemplate):
            return self._non_existing_templates(template.template)

        raise RuntimeError(f"Unknown template type: {type(template)}")

    def _validate_state_templates(self, state_machine_class: type[GenieStateMachine]):
        templates = state_machine_class.templates
        states_without_template = {
            state.id
            for state in state_machine_class.states
            if isinstance(state, State) and state.id not in templates
        }

        unknown_template_names = self._non_existing_templates(
            [
                templates[state.id]
                for state in state_machine_class.states
                if state not in states_without_template
            ]
        )

        if states_without_template or unknown_template_names:
            raise ValueError(
                f"GenieStateMachine {state_machine_class} is missing templates for states: ["
                f"{', '.join(states_without_template)}] and "
                f"cannot find templates with names: [{', '.join(unknown_template_names)}]"
            )

    def _validate_state_values(self, state_machine_class: type[GenieStateMachine]):
        state_values = [state.value for state in state_machine_class.states]
        state_values_set = set(state_values)
        duplicate_values = set()
        for state_value in state_values:
            try:
                state_values_set.remove(state_value)
            except KeyError:
                duplicate_values.add(state_value)

        if len(duplicate_values) > 0:
            raise ValueError(
                f"For GenieStateMachine {state_machine_class}, "
                f"the following values are duplicates: {duplicate_values}")

    def register_model(self, model_key: str, model_class: Type[BaseModel]):
        """
        Register a model class, so it can be stored in the object store. Also registers
        the model with the given model_key for the API.

        :param model_key: the key at which the genie flow is reachable for the given model_class
        :param model_class: the class of the model that needs to be registered
        """
        if not issubclass(model_class, GenieModel):
            raise ValueError(
                f"Can only register subclasses of GenieModel, not {model_class}"
            )

        self._validate_state_values(model_class.get_state_machine_class())
        self._validate_state_templates(model_class.get_state_machine_class())

        if model_key in self.model_key_registry:
            raise ValueError(f"Model key {model_key} already registered")

        self.model_key_registry[model_key] = model_class

    def _create_invoker_registration(
            self,
            directory_path: Path,
            invoker_config: dict,
    ) -> _RegisteredDirectory:
        nr_invokers = (
            self.pool_size
            if "pool_size" not in invoker_config
            else invoker_config["pool_size"]
        )
        return _RegisteredDirectory(
            directory=directory_path,
            config=invoker_config,
            jinja_loader=jinja2.FileSystemLoader(directory_path),
            invokers=self.invoker_factory.create_invoker_pool(
                nr_invokers,
                invoker_config,
            ),
        )

    def _create_renderer_registration(
            self,
            directory_path: Path,
            renderer_config: dict,
    ) -> _RegisteredDirectory:
        return _RegisteredDirectory(
            directory=directory_path,
            jinja_loader=jinja2.FileSystemLoader(directory_path),
            config=renderer_config,
            invokers=None,
        )

    def register_template_directory(self, prefix: str, directory: str | PathLike):
        if prefix in self._template_directories:
            raise ValueError(f"Template prefix '{prefix}' already registered")

        directory_path = Path(directory).resolve()
        config = self._walk_directory_tree_upward(directory_path, self.read_meta)

        if "invoker" in config and "renderer" in config:
            logger.error(
                "Compiled template directory {directory_path} configuration "
                "contains both 'invoker' and 'renderer'",
                directory_path=directory_path,
            )
            raise ValueError(
                f"Compiled template directory {directory_path} configuration "
                "contains both 'invoker' and 'renderer'"
            )

        if "invoker" in config:
            self._template_directories[prefix] = self._create_invoker_registration(
                directory_path,
                config["invoker"],
            )
        elif "renderer" in config:
            self._template_directories[prefix] = self._create_renderer_registration(
                directory_path,
                config["renderer"],
            )
        else:
            logger.error(
                "Compiled template directory {directory_path} configuration "
                "does not contain 'invoker' or 'renderer'",
                directory_path=directory_path,
            )
            raise ValueError(
                f"Compiled template directory {directory_path} configuration "
                "does not contain 'invoker' or 'renderer'"
            )

        self._jinja_env = None  # clear the Environment

    def has_invoker(self, template: CompositeTemplateType) -> bool:
        if not isinstance(template, str):
            return True

        prefix, _ = template.rsplit("/", 1)
        return self._template_directories[prefix]["invokers"] is not None

    def get_template(self, template_path: str) -> jinja2.Template:
        return self.jinja_env.get_template(template_path)

    def render_template(self, template_path: str, data_context: dict[str, Any]) -> str:
        template = self.jinja_env.get_template(template_path)
        rendered =  template.render(data_context)
        logger.debug(
            "rendered template {template_path} into {rendered}",
            template_path=template_path,
            rendered=rendered,
        )
        return rendered

    def invoke_template(
        self,
        template_path: str,
        data_context: dict[str, Any],
    ) -> str:
        rendered = self.render_template(template_path, data_context)

        prefix, _ = template_path.rsplit("/", 1)
        invokers_pool = self._template_directories[prefix]["invokers"]
        if invokers_pool is None:
            logger.error(
                "no invokers registered for template {template_path}",
                template_path=template_path,
            )
            raise ValueError(f"no invokers registered for template {template_path}")

        with invokers_pool as invoker:
            return invoker.invoke(rendered)

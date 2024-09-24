from os import PathLike
from pathlib import Path
from typing import TypedDict, Callable, Optional, TypeVar, Any, Type

import jinja2
from loguru import logger
import yaml
from celery import Task
from jinja2 import Environment, PrefixLoader, TemplateNotFound
from pydantic_redis import Model
from statemachine import State

from genie_flow.genie import GenieModel, GenieStateMachine
from genie_flow_invoker import InvokersPool
from genie_flow_invoker.factory import InvokerFactory
from genie_flow.model.types import ModelKeyRegistryType
from genie_flow.model.template import CompositeTemplateType
from genie_flow.store import StoreManager

_META_FILENAME: str = "meta.yaml"
_T = TypeVar("_T")


class _TemplateDirectory(TypedDict):
    directory: Path
    config: dict
    jinja_loader: jinja2.FileSystemLoader
    invokers: InvokersPool


class GenieEnvironment:
    """
    The `GenieEnvironment` deals with maintaining the templates registry, rendering templates
    and invoking `Invoker`s with a data context and a dialogue.
    """

    def __init__(
        self,
        template_root_path: str | PathLike,
        pool_size: int,
        store_manager: StoreManager,
        model_key_registry: ModelKeyRegistryType,
        invoker_factory: InvokerFactory,
    ):
        self.template_root_path = Path(template_root_path).resolve()
        self.pool_size = pool_size
        self.store_manager = store_manager
        self.model_key_registry = model_key_registry
        self.invoker_factory = invoker_factory

        self._jinja_env: Optional[Environment] = None
        self._template_directories: dict[str, _TemplateDirectory] = {}

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

    def register_model(self, model_key: str, model_class: Type[Model]):
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

        self.store_manager.register_model(model_class)
        self.model_key_registry[model_key] = model_class

    def register_template_directory(self, prefix: str, directory: str | PathLike):
        if prefix in self._template_directories:
            raise ValueError(f"Template prefix '{prefix}' already registered")

        directory_path = Path(directory).resolve()
        config = self._walk_directory_tree_upward(directory_path, self.read_meta)
        nr_invokers = (
            self.pool_size if "pool_size" not in config else config["pool_size"]
        )
        self._template_directories[prefix] = _TemplateDirectory(
            directory=directory_path,
            config=config,
            jinja_loader=jinja2.FileSystemLoader(directory),
            invokers=self.invoker_factory.create_invoker_pool(nr_invokers, config["invoker"]),
        )
        self._jinja_env = None  # clear the Environment

    def get_template(self, template_path: str) -> jinja2.Template:
        return self.jinja_env.get_template(template_path)

    def render_template(self, template_path: str, data_context: dict[str, Any]) -> str:
        template = self.jinja_env.get_template(template_path)
        return template.render(data_context)

    def invoke_template(
        self,
        template_path: str,
        data_context: dict[str, Any],
    ) -> str:
        rendered = self.render_template(template_path, data_context)
        prefix, _ = template_path.rsplit("/", 1)
        invokers_pool = self._template_directories[prefix]["invokers"]
        logger.debug("rendered template into: {}", rendered)
        with invokers_pool as invoker:
            return invoker.invoke(rendered)

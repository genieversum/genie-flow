import logging
from os import PathLike
from pathlib import Path
from queue import Queue
from typing import TypedDict, Callable, Optional, Literal, TypeVar, Any

import jinja2
import yaml
from jinja2 import Environment, PrefixLoader

from ai_state_machine.invoker import GenieInvoker, create_genie_invoker
from ai_state_machine.model import DialogueElement

_META_FILENAME: Literal["meta.yaml"]
_T = TypeVar("_T")


class InvokersPool:
    """
    A simple context manager that gets invokers from a queue and returns them when the
    context is closed. Makes the queue serve as a pool of invokers.
    """

    def __init__(self, queue: Queue[GenieInvoker]):
        self._queue = queue
        self._current_invoker: Optional[GenieInvoker] = None

    def __enter__(self):
        if self._current_invoker is None:
            self._current_invoker = self._queue.get()
        return self._current_invoker

    def __exit__(self, exc_type, exc_value, exc_tb):
        if self._current_invoker is not None:
            self._queue.put(self._current_invoker)
            self._current_invoker = None


class _TemplateDirectory(TypedDict):
    directory: Path
    config: dict
    jinja_loader: jinja2.FileSystemLoader
    invokers: InvokersPool


class GenieEnvironment:
    def __init__(
            self,
            template_root_path: str | PathLike,
            pool_size: int = 1,
    ):
        self.template_root_path = Path(template_root_path)
        self.pool_size = pool_size
        self._jinja_env: Optional[Environment] = None
        self._template_directories: dict[str, _TemplateDirectory] = {}

    def _walk_directory_tree_upward(
            self,
            start_directory: Path,
            execute: Callable[[Path, Optional[dict]], _T]
    ) -> _T:
        start_directory = start_directory.resolve()
        if start_directory == self.template_root_path:
            return execute(start_directory, None)
        if start_directory == Path.root:
            raise ValueError("start_directory not part of the template directory tree")
        parent_directory = start_directory.parent
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
            logging.debug(f"No meta file found in {directory}")
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
            self._jinja_env = Environment(loader=PrefixLoader(self.jinja_loader_mapping))
        return self._jinja_env

    def _create_invoker_pool(self, config: dict[str]) -> InvokersPool:
        queue = Queue()
        nr_invokers = self.pool_size if "pool_size" not in config else config["pool_size"]
        assert nr_invokers > 0, f"Should not create invoker pool of size {nr_invokers}"

        for _ in range(nr_invokers):
            queue.put(create_genie_invoker(config))

        return InvokersPool(queue)

    def register_template_directory(self, prefix: str, directory: str | PathLike):
        if prefix in self._template_directories:
            raise ValueError(f"Template prefix '{prefix}' already registered")

        directory_path = Path(directory).resolve()
        config = self._walk_directory_tree_upward(directory_path, self.read_meta)
        self._template_directories[prefix] = _TemplateDirectory(
            directory=directory_path,
            config=config,
            jinja_loader=jinja2.FileSystemLoader(directory),
            invokers=self._create_invoker_pool(config["invoker"])
        )
        self._jinja_env = None  # clear the Environment

    def render_template(self, template_path: str, data_context: dict[str, Any]) -> str:
        template = self.jinja_env.get_template(template_path)
        return template.render(data_context)

    def invoke_template(
            self,
            template_path: str,
            data_context: dict[str, Any],
            dialogue: Optional[list[DialogueElement]] = None
    ) -> str:
        rendered = self.render_template(template_path, data_context)
        prefix, _ = template_path.rsplit("/", 1)
        invokers_pool = self._template_directories[prefix]["invokers"]
        with invokers_pool as invoker:
            return invoker.invoke(rendered, dialogue)

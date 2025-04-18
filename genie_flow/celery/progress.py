from celery import Task
from dependency_injector.wiring import inject, Provide
from loguru import logger

from genie_flow.containers.persistence import GenieFlowPersistenceContainer
from genie_flow.session_lock import SessionLockManager


class ProgressLoggingTask(Task):

    @inject
    def update_progress(
        self,
        session_id: str,
        lock_manager: SessionLockManager = (
            Provide[GenieFlowPersistenceContainer.session_lock_manager]
        ),
    ):
        lock_manager.progress_update_done(session_id)

    @inject
    def remove_progress(
        self,
        session_id: str,
        lock_manager: SessionLockManager = (
            Provide[GenieFlowPersistenceContainer.session_lock_manager]
        ),
    ):
        lock_manager.progress_done(session_id)

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"Just finished task {task_id} successfully.")
        logger.debug(f"Task {task_id} has return value: {retval}")
        session_id: str = args[-2]
        self.update_progress(session_id)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Task {task_id} failed with {exc}")
        session_id: str = args[-2]
        self.remove_progress(session_id)

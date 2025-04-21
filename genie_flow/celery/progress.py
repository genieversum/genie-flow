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
        lock_manager.progress_finished(session_id)

    def on_success(self, retval, task_id, args, kwargs):
        session_id: str = args[-2]
        logger.info(
            "Just finished task {task_id} successfully, for session {session_id}",
            task_id=task_id,
            session_id=session_id,
        )
        logger.debug(
            "Task {task_id} has return value: {retval}",
            task_id=task_id,
            retval=retval,
        )
        self.update_progress(session_id)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        session_id: str = args[-2]
        logger.error(
            "Task {task_id} for session {session_id} failed with {exc}",
            task_id=task_id,
            session_id=session_id,
            exc=exc,
        )
        self.remove_progress(session_id)

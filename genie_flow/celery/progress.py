from celery import Task
from loguru import logger

from genie_flow.session_lock import SessionLockManager


class ProgressLoggingTask(Task):
    """
    This is a celery task that logs the progress of a session.
    It also updates the progress of the session in the session lock manager.
    """
    session_lock_manager: SessionLockManager

    def on_success(self, retval, task_id, args, kwargs):
        session_id: str = args[-3]
        invocation_id: str = args[-1]

        logger.info(
            "Just finished task {task_id} successfully, "
            "for session {session_id} invocation {invocation_id}",
            task_id=task_id,
            session_id=session_id,
            invocation_id=invocation_id,
        )
        logger.debug(
            "Task {task_id} has return value: {retval}",
            task_id=task_id,
            retval=retval,
        )
        self.session_lock_manager.progress_update_done(session_id, invocation_id)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        session_id: str = args[-3]
        invocation_id: str = args[-1]

        logger.error(
            "Task {task_id} for session {session_id} invocation {invocation_id} "
            "failed with {exc}",
            task_id=task_id,
            session_id=session_id,
            invocation_id=invocation_id,
            exc=exc,
        )
        self.session_lock_manager.progress_update_done(session_id, invocation_id)

from typing import Optional

import redis_lock
from celery import Task
from dependency_injector.wiring import inject, Provide
from loguru import logger

from genie_flow.containers.persistence import GenieFlowPersistenceContainer
from genie_flow.genie import GenieTaskProgress
from genie_flow.session_lock import SessionLockManager


class ProgressLoggingTask(Task):

    @inject
    def get_lock_for_session(
            self,
            session_id: str,
            lock_manager: SessionLockManager = (
                    Provide[GenieFlowPersistenceContainer.session_lock_manager]
            ),
    ) -> redis_lock.Lock:
        return lock_manager._create_lock_for_session(session_id)

    @staticmethod
    def _retrieve_progress(session_id) -> Optional[GenieTaskProgress]:
        task_progress_list = GenieTaskProgress.select(ids=[session_id])
        if task_progress_list is None or len(task_progress_list) == 0:
            logger.warning("No progress record for session {}", session_id)
            return None

        if len(task_progress_list) > 1:
            logger.error(
                f"Found too many tasks progress records for session {session_id};"
                f" should be exactly one"
            )

        return task_progress_list[0]

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"Just finished task {task_id} successfully.")
        logger.debug(f"Task {task_id} has return value: {retval}")
        session_id: str = args[-1]
        with self.get_lock_for_session(session_id):
            task_progress = self._retrieve_progress(session_id)
            if task_progress is None:
                return

            task_progress.nr_subtasks_executed += 1
            GenieTaskProgress.update(
                session_id,
                {"nr_subtasks_executed": task_progress.nr_subtasks_executed},
            )
            logger.debug(
                "session {} has now done {} tasks",
                session_id,
                task_progress.nr_subtasks_executed,
            )

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Task {task_id} failed with {exc}")
        session_id: str = args[-1]
        with self.get_lock_for_session(session_id):
            self._retrieve_progress(session_id)
            GenieTaskProgress.delete(session_id)

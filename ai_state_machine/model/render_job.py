from dataclasses import dataclass
from typing import Any

from ai_state_machine.model.template import CompositeTemplateType


@dataclass
class TemplateRenderJob:
    """
    When an object of this class is returned from an action on a state machine, the template
    will be rendered with the render_data. The output of all actions in one transaction will
    be assigned to model.actor_input, divided by '\n' characters.
    """
    template: CompositeTemplateType
    session_id: str
    render_data: dict[str, Any]


@dataclass
class EnqueuedRenderJob(TemplateRenderJob):
    """
    When an object of this class is returned from an action on a state machine, the template
    is rendered with the render_data and a Celery task is compiled and scheduled. As the last
    action of that task, this state machine is sent the `event_to_send_after` to automatically
    start a new transition.
    """
    model_fqn: str
    event_to_send_after: str

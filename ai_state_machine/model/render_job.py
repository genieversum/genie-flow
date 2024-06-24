from dataclasses import dataclass
from typing import Any

from ai_state_machine.model.template import CompositeTemplateType


@dataclass
class TemplateRenderJob:
    template: CompositeTemplateType
    session_id: str
    render_data: dict[str, Any]


@dataclass
class EnqueuedRenderJob(TemplateRenderJob):
    model_fqn: str
    event_to_send_after: str

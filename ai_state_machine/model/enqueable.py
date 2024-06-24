from dataclasses import dataclass
from typing import Any

from ai_state_machine.model.template import CompositeTemplateType


@dataclass
class Enqueable:
    template: CompositeTemplateType
    model_fqn: str
    session_id: str
    render_data: dict[str, Any]
    event_to_send_after: str

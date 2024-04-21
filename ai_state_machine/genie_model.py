from typing import Optional

from pydantic import Field
from pydantic_redis import Model

from ai_state_machine.genie_state_machine import GenieStateMachine
from ai_state_machine.model import DialogueElement, DialogueFormat


class GenieModel(Model):
    """
    The base model for all models that will carry data in the dialogue. Contains the attributes
    that are required and expected by the `GenieStateMachine` such as `state` and `session_id`/

    This class also carries the dialogue - a list of `DialogueElement`s of the previous chat.

    And it carries a number of state-dependent attributes that are important to the progress of
    the dialogue, such as `running_task_id` which indicates if there is a currently running task,
    as well as `actor` and `actor_text`, both indicators for the most recent interaction.

    This class is a subclass of the pydantic_redis `Model` class, which makes it possible to
    persist the values into Reids and retrieve it again by its primary key. The attribute
    `_primary_key_field` is used to determine the name of the primary key.
    """
    _primary_key_field: str = "session_id"

    state: str | int | None = Field(
        None,
        description="The current state that this model is in, represented by the value of the state"
    )
    session_id: str = Field(
        description="The ID of the session this claims belongs to."
    )
    dialogue: list[DialogueElement] = Field(
        default_factory=list,
        description="The list of dialogue elements that have been used in the dialogue so far",
    )
    running_task_id: Optional[str] = Field(
        None,
        description="the (Celery) task id of the currently running task",
    )
    actor: Optional[str] = Field(
        None,
        description="The actor that has created the current input",
    )
    actor_input: str = Field(
        "",
        description="the most recent received input from the actor",
    )

    @property
    def state_machine_class(self) -> type["GenieStateMachine"]:
        """
        Property that returns the class of the state machine that this model should be
        managed by.
        """
        raise NotImplementedError()

    def create_state_machine(self) -> "GenieStateMachine":
        """
        Create and return a newly instantiated state machine, of the appropirate class,
        that manages this instance of a model.
        """
        return self.state_machine_class(model=self)

    @property
    def current_response(self) -> Optional[DialogueElement]:
        """
        Return the most recent `DialogueElement` from the dialogue list.
        """
        return self.dialogue[-1] if len(self.dialogue) > 0 else None

    def format_dialogue(self, target_format: DialogueFormat) -> str:
        """
        Apply the given target format to the dialogue of this instance.
        """
        return DialogueFormat.format(self.dialogue, target_format)

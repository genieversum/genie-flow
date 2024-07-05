import json
from typing import Optional, Any, Iterable

from loguru import logger
from pydantic import Field
from pydantic_redis import Model
from statemachine import StateMachine, State
from statemachine.event_data import EventData

from ai_state_machine.model.dialogue import DialogueElement, DialogueFormat
from ai_state_machine.model.template import CompositeTemplateType


class GenieModel(Model):
    """
    The base model for all models that will carry data in the dialogue. Contains the attributes
    that are required and expected by the `GenieStateMachine` such as `state` and `session_id`/

    This class also carries the dialogue - a list of `DialogueElement`s of the chat so far.

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
        description="The current state that this model is in, represented by the state's value",
    )
    session_id: str = Field(
        description="The ID of the session this data model object belongs to."
    )
    dialogue: list[DialogueElement] = Field(
        default_factory=list,
        description="The list of dialogue elements that have been used in the dialogue so far",
    )
    running_task_ids: int = Field(
        default=0,
        description="the number of Celery tasks that are currently running for this model",
    )
    task_error: Optional[str] = Field(
        default=None,
        description="The error message returned from a running task",
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
    def has_running_tasks(self) -> bool:
        return self.running_task_ids > 0

    @property
    def has_errors(self) -> bool:
        return self.task_error is not None

    def add_running_task(self, task_id: str):
        self.running_task_ids += 1

    def remove_running_task(self, task_id: str):
        self.running_task_ids -= 1
        if self.running_task_ids < 0:
            raise ValueError(f"removed too many running tasks")

    @classmethod
    def get_state_machine_class(cls) -> type["GenieStateMachine"]:
        """
        Property that returns the class of the state machine that this model should be
        managed by.
        """
        raise NotImplementedError()

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

    def add_dialogue_element(self, actor: str, actor_text: str):
        element = DialogueElement(actor=actor, actor_text=actor_text)
        self.dialogue.append(element)


class GenieStateMachine(StateMachine):
    """
    A State Machine class that is able to manage an AI driven dialogue and extract information
    from it. The extracted information is stored in an accompanying data model (based on the
    `GenieModel` class).
    """

    # EVENTS that need to be specified
    user_input: Any = None
    ai_extraction: Any = None
    advance: Any = None

    # TEMPLATE mapping that needs to be specified
    templates: dict[str, CompositeTemplateType] = dict()

    def __init__(
        self,
        model: GenieModel,
    ):
        self.current_template: Optional[CompositeTemplateType] = None
        super(GenieStateMachine, self).__init__(model=model)

    @property
    def render_data(self) -> dict[str, str]:
        """
        Returns a dictionary containing all data that can be used to render a template.

        It will contain:
        - "state_id": The ID of the current state of the state machine
        - "state_name": The name of the current state of the state machine
        - "dialogue" The string output of the current dialogue
        - all keys and values of the machine's current model
        """
        render_data = self.model.model_dump()
        try:
            parsed_json = json.loads(self.model.actor_input)
        except json.JSONDecodeError:
            parsed_json = None

        render_data.update(
            {
                "parsed_actor_input": parsed_json,
                "state_id": self.current_state.id,
                "state_name": self.current_state.name,
                "chat_history": str(self.model.format_dialogue(DialogueFormat.CHAT)),
            }
        )
        return render_data

    def get_template_for_state(self, state: State) -> CompositeTemplateType:
        """
        Retrieve the template for a given state. Raises an exception if the given
        state does not have a template defined.

        :param state: The state for which to retrieve the template for
        :return: The template for the given state
        :raises AttributeError: If this object does not have an attribute that carries the templates
        :raises KeyError: If there is no template defined for the given state
        """
        try:
            return self.templates[state.id]
        except KeyError:
            logger.error(f"No template for state {state.id}")
            raise

    # EVENT HANDLERS
    def before_transition(self, event_data: EventData):
        """
        Set the current actors input and the current rendering for the target state.
        It is assumed that the event data that is provided to the event
        that started this transition is the actor input.

        Triggered when an event is received, right before the current state is exited.

        This method takes the events first argument and places that in `self.actor_input`. This
        makes it available for further processing.

        It will also take the rendering of the target template and stores that into
        `self.current_rendering` for further processing.

        If the event data does not contain the actor input, the actor is reset to an empty
        string.

        :param event_data: the event data that was provided to start this transition
        """
        try:
            self.model.actor_input = event_data.args[0]
            logger.debug("setting the actor input to: {}", self.model.actor_input)
        except (TypeError, IndexError):
            logger.debug("Starting a transition without an actor input")
            self.model.actor_input = ""

        self.current_template = self.get_template_for_state(event_data.target)

    def after_transition(self, state: State, **kwargs):
        """
        A generic hook that gets called after a transition has been completed. This is used
        to add to the dialogue a new `DialogueElement` with the current actor and actor input.
        """
        logger.info(f"== concluding transition into state {state.name} ({state.id})")

        if self.model.actor is not None:
            logger.debug("Adding a dialogue element to the dialogue")
            self.model.dialogue.append(
                DialogueElement(
                    actor=self.model.actor,
                    actor_text=self.model.actor_input,
                )
            )
            self.model.actor = None
            self.model.actor_input = None

    # VALIDATIONS AND CONDITIONS
    def is_valid_response(self, event_data: EventData):
        logger.debug(f"is valid response {event_data.args}")
        return all(
            [
                event_data.args is not None,
                len(event_data.args) > 0,
                event_data.args[0] is not None,
                event_data.args[0] != "",
            ]
        )

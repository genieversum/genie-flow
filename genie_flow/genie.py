import datetime
import enum
import json
from functools import cached_property, cache
from typing import Optional, Any

from loguru import logger
from pydantic import Field, BaseModel, ConfigDict, computed_field
from statemachine import StateMachine, State
from statemachine.event_data import EventData

from genie_flow.model.dialogue import DialogueElement, DialogueFormat
from genie_flow.model.secondary_store import SecondaryStore
from genie_flow.model.template import CompositeTemplateType
from genie_flow.model.versioned import VersionedModel


class StateType(enum.IntEnum):
    USER = 0
    INVOKER = 1

    @property
    def as_actor(self) -> str:
        match self:
            case StateType.INVOKER:
                return "assistant"
            case StateType.USER:
                return "user"
            case _:
                raise ValueError("Unknown State Type")


class DialoguePersistence(enum.IntEnum):
    NONE = 0
    RAW = 1
    RENDERED = 2


class GenieModel(VersionedModel):
    """
    The base model for all models that will carry data in the dialogue. Contains the attributes
    that are required and expected by the `GenieStateMachine` such as `state` and `session_id`/

    This class also carries the dialogue - a list of `DialogueElement`s of the chat so far.

    And it carries a number of state-dependent attributes that are important to the progress of
    the dialogue, such as `running_task_id` which indicates if there is a currently running task,
    as well as `actor` and `actor_text`, both indicators for the most recent interaction.

    This class is a subclass of the pydantic_redis `Model` class, which makes it possible to
    persist the values into Redis and retrieve it again by its primary key. The attribute
    `_primary_key_field` is used to determine the name of the primary key.
    """

    seed_data: Optional[str] = Field(
        default=None,
        description="A string to seed the newly created session object with",
    )
    state: str | int | None = Field(
        default=None,
        description="The current state that this model is in, represented by the state's value",
    )
    session_id: str = Field(
        description="The ID of the session this data model object belongs to."
    )
    source_type: Optional[StateType] = Field(
        default=None,
        description="The type of state that the most recent transition is from",
    )
    target_type: Optional[StateType] = Field(
        default=None,
        description="The type of state that the most recent transition is to",
    )
    dialogue_persistence: Optional[DialoguePersistence] = Field(
        default=None,
        description="Indicator to how to add most recent actor input to the dialogue",
    )
    dialogue: list[DialogueElement] = Field(
        default_factory=list,
        description="The list of dialogue elements that have been used in the dialogue so far",
    )
    task_error: Optional[str] = Field(
        default=None,
        description="The error message returned from a running task",
    )
    actor: Optional[str] = Field(
        default=None,
        description="The actor that has created the current input",
    )
    actor_input: str = Field(
        default="",
        description="the most recent received input from the actor",
    )
    secondary_storage: SecondaryStore = Field(
        default_factory=SecondaryStore,
        description="A dictionary that can be used to store secondary information about the session",
    )

    def model_post_init(self, context: Any, /) -> None:
        """
        Overriding this method to call the `seed_model` method and clear the seeding_data
        property. When data passed as seeding_data is required, developers should override
        the `seed_model` method.

        :param context: any context that was created during model validations
        """
        if self.seed_data is None:
            logger.debug(
                "No seeding data passed for {cls} with session {session_id}",
                cls=str(self.__class__),
                session_id=self.session_id,
            )
            return
        logger.debug(
            "Seeding model data for {cls} with session {session_id}",
            cls=str(self.__class__),
            session_id=self.session_id,
        )
        self.seed_model()
        self.seed_data = None

    def seed_model(self):
        """
        By overriding this method, developers can seed a newly created instance of the
        Genie Model from any seeding data that was passed. That seed data will be assigned
        to the property `seeding_data`, which is a string.
        """
        pass

    @property
    def render_data(self) -> dict[str, Any]:
        """
        Returns a dictionary containing all data that can be used to render a template.

        **NOTE** We are using the `serialize_as_any` flag here to make sure that properties
        in the `secondary_storage` are also included.

        It will contain:
        - "state_id": The ID of the current state of the state machine
        - "current_datetime": The ISO 8601 formatted current date and time in UTC
        - "dialogue" The string output of the current dialogue
        - all keys and values of the machine's current model
        """
        render_data = self.model_dump(serialize_as_any=True)
        try:
            parsed_json = json.loads(self.actor_input)
        except json.JSONDecodeError:
            parsed_json = None

        render_data.update(
            {
                "parsed_actor_input": parsed_json,
                "state_id": self.state,
                "current_datetime": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "chat_history": str(self.format_dialogue(DialogueFormat.YAML)),
            }
        )
        return render_data

    @property
    def has_errors(self) -> bool:
        return self.task_error is not None

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
        """
        Add a given actor and actor text to the dialogue.
        :param actor: the name of the actor
        :param actor_text: the actor text
        """
        element = DialogueElement(actor=actor, actor_text=actor_text)
        self.dialogue.append(element)

    def record_dialogue_element(self):
        """
        Record the current `actor` and `actor_input` into the dialogue.
       """
        self.add_dialogue_element(self.actor, self.actor_input)


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
    def render_data(self) -> dict[str, Any]:
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
                "chat_history": str(self.model.format_dialogue(DialogueFormat.YAML)),
            }
        )
        return render_data

    def get_template_for_state(self, state: State) -> CompositeTemplateType:
        """
        Retrieve the template for a given state. Raises an exception if the given
        state does not have a template defined.

        :param state: The state for which to retrieve the template for
        :return: The template for the given state
        :raises AttributeError: If this ob`ject does not have an attribute that carries the templates
        :raises KeyError: If there is no template defined for the given state
        """
        try:
            return self.templates[state.id]
        except KeyError:
            logger.error(f"No template for state {state.id}")
            raise

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

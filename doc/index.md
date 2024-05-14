# Genie Flow
The Genie Flow Framework is intended to make it easy to design and implement dialogues between a
Human user and an LLM. Such dialogue is typically directed through a number of stages. Often they
start with a preamble, then some information retrieval, some conclusion building and an epilogue.

Keeping that state in check: what prompt should be used, given what has been discussed so far, is
not trivial. And when implemented using simple if / then / else logic, the code becomes hard to 
maintain.https://about.gitlab.com/releases/2024/05/08/patch-release-gitlab-16-11-2-released/

This package aims to simplify and streamline the creation of dialogue flows that have a user
interact with an LLM.

The main concept of Genie Flow is to maintain a State Machine, coupled with a Data Object.
The State Machine to direct the flow and determine which prompts to invoke when during the
conversation. The Data Object to carry all data that is gathered during the conversation.

These are only two classes that a developer would need to implement. The Genie Flow framework
takes care of creating sessions, persisting data, maintaining the dialogue history, calling
the LLMs asynchronously, and other feats.

## Genie Model
This is just a [pydantic](https://docs.pydantic.dev/latest/) model that can have as many fields as
one needs. A developer would subclass the `GenieModel` class, which adds a number of required
fields and methods. That `GenieModel` class also implements all functionality to persist it into
a Redis database. That functionality is based on the package [Pydantic-Redis](https://sopherapps.github.io/pydantic-redis/)
which implements the necessary ORM functionality.

### data object class fields

`state`
: This is the current state the accompanying State Machine is in. It is a string or an integer.
Best not to be touched by the developer.

`session_id`
: The unique id of a session that this Data Object belongs to. Best not to be touched by the
developer.

`dialogue`
: A list of `DialogueElement`s that is the sequence of uttering by the different actors involved
in the dialogue.

`running_task_id`
: The optional id of a [Celery](https://docs.celeryq.dev/en/stable/getting-started/introduction.html)
task that may be running as part of the dialogue. This could be, for instance, an LLM call that
has been triggered by a user input.

`actor`
: The name of the actor that has most recently uttered a statement. By default, this is `USER` for
a Human actor and `LLM` for an LLM.

`actor_input`
: The input that was last uttered by the most recent actor.

### data object methods and properties

The developer needs to override the property `state_machine_class` which should return the class
that implements the State Machine that accompanies this Data Object. The method 
`create_state_machine` will use the `state_machine_class` property to instantiate a new State
Machine and connect it to an instance of this Data Object.

Some convenience methods exist:

`current_response`
: A property that returns the most recent uttering of an actor. Or `None` if there is none.

`format_dialogue`
: Returns a string representation of the dialogue, using some pre-defined formats. See the 
`DialogueFormat` class for more details.

### related objects
If a developed needs to maintain a relation to other objects that are not base classes, the class
of that other object also needs to be ORM-able. This is achieved by inheriting that other class
not from `BaseModel` as is done for Pydantic, but by inheriting from `Model` which comes from the
Pydantic-Redis package.

This also means that this other object needs to have a class property called `_primary_key_field`
which is the name of the field that uniquely identified an instance of that object.

For example, the `DialogeElement` class (of which the `GenieModel` maintains a list) is implemented
as follows:

```python
import uuid

from pydantic import Field
from pydantic_redis import Model

class DialogueElement(Model):
    _primary_key_field = "id"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    
    # other fields and methods
```

And with that implementation, the `GenieModel` can now maintain a list of `DialogueElement`s that
are then also persisted into Redis. Like so:

```python
from pydantic import Field
from pydantic_redis import Model

class GenieModel(Model):
    _primary_key_field: str = "session_id"

    dialogue: list["DialogueElement"] = Field(
        default_factory=list
    )

    # other fields and methods
```

### Registering Models
When the developed has created a new `GenieModel`, that new model needs to be registered. This will
make that model recognized to the Pydantic-Redis ORM framework. This registration is done as follows:

```python
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.store import STORE

class MyNewModel(GenieModel):
    ...

STORE.register_model(MyNewModel)
```

From that point onwards, the class `MyNewModel` can be persisted and therefore used by the Genie
Flow framework.

Remember that this also needs to be done for any additional models that may be referred to by this
`MyNewModel` class.

## Genie Flow state machine principles
The backbone of the Genie Flow framework is defined by the State Machine. The Genie Flow State
Machine is based on the package [Python State Machine](https://python-statemachine.readthedocs.io/en/latest/)
and the `GenieStateMachine` is a direct subclass of the `StateMachine` class that is defined there.

The `GenieStateMachine` class implements the base logic of the Genie Flow. A State Machine defined
the different states (nodes in a graph) and the transitions (edges in the graph) that can be made
between these states.

### Question and Answer example
A simple Question and Answer dialogue flow would look like this:

![state diagram of simple Q and A](../example_qa.q_and_a.QandAModel.png)

Here it becomes apparent that a dialogue is played between an "AI" and a human actor. The
dialogue stars with the initial state (color coded) called `Intro`. From that initial state
the only transition that can be made is the one called `user_input`, which transitions into
`Ai creates response`. From there, a transition called `ai_extraction` brings the state
machine into the state called `User enters query`. From there, the only transition is again
a `user_input` transition, back to the `Ai creates response`.

This example shows a number of foundational elements:

states
: A state machine contains a number of states between which the state machine can transition.
A machine can only be in one state at any single time. The transitions that can be made from
one state to another are predefined and fixed. Only one initial state is defined. It is the
state where a newly instantiated state machine starts in.

transitions
: From any state there can be zero, one or more transitions into other states. If there are
zero states, that state is a final state, of which there can be multiple, or none as in the
Q and A example. Every transition has the name of an event, which is the event that will
trigger that particular transition.

events
: An event is what makes the state machine transition from one state to the next. In Genie
Flow, events are either sent through the API or received from the internal workings, for 
instance, when an LLM has finished rendering, and it's output is ready for processing.

### Question and Answer example with conditions
This first example gives a good impression of the elements that are relevant for creating a
Genie Flow application. The dialogue, however, is simplistic and never-ending. Now, consider
the following flow diagram:

![state diagram of Q and A with conditions](../example_qa.q_and_a_cond.QandACondModel.png)

It is almost the same Question and Answer flow, except that we have now introduced conditions.
There are now two `ai_extraction` event transitions from the state `Ai creates response`. One
that has the connotation `user_wants_to_quit` and the other with `!user_wants_to_quit`.
Indicating that the user wants to quit, or the user does not want to quit - indicated by 
the `!` mark, pronounced as "not".

So when the LLM determines the user wants to quit, we want the flow to go to the state called
"Outro". If not, we follow the normal path towards the state "User enters query".

A similar thing has been done with the `user_input` events out of the state "User enters query".
Here we have another condition called `user_says_stop` that tells the state machine to either
go to the "Ai creates response", in the case where "Not user says stop" (`!user_says_stop`),
or to the state "Outro" in the case where "user says stop" (`user_says_stop`).

These conditions are a first step towards creating more complex dialogues. It enables us to
make different paths through the dialogue.

### Question and Answer example with data capture
So far we have not yet seen how data that is entered by the user is captured and stored. Now
imagine the following Genie Flow:

![state diagram of Q and A with data capture](../example_qa.q_and_a_capture.QandACaptureModel.png)

In this flow, the user is asked for their name. That username is extracted and stored in the
data model. The extraction is done through an LLM. The response of that LLM should be either
the name of the user or the term `UNDEFINED`. In the latter case, the user is asked again to
state their name (state `Need to retry`). The condition `name_is_defined` ensures the state 
machine directs the user towards the Welcome message or that retry.

One new element on state `Ai extracts name` is the `exit / on_exit_ai_extracts_name` method.
This is the method that is called when the state machine exists the state `Ai extracts name`.
So this is when the LLM has conducted it extraction and the response is available. This is the
moment during the conversation that the programmer has control to change values in the data
model attached to the state machine.

actions
: When entering or exiting states, the programmer has control over what happens. Typically,
these moments are used to capture responses from the LLM or users and adapt the content of an
attached data model object.

### Genie Flow templating
The final concept that is introduced by Genie Flow is the idea that every state maintains a
template. That could be a template to construct the text that should be sent to the user or
the template that is used to construct the text that is sent to the LLM.

The flow is as follows:
![flow of actions of rendering the template](templating-flow.drawio.svg)

When the state machine traverses from one state to the next, Genie Flow takes the template that
is attached to the target state, renders the template with the data model object and provides
it to the actor that needs it. If the event triggering the transition is a `user_input` event,
then the next actor is an LLM. In case the event for the transition is `ai_extraction` then the
next actor is the user.

For templating, Genie Flow uses [Jinja2](https://jinja.palletsprojects.com/en/3.1.x/), a powerful
templating engine.

When rendering the template, all attributes of the data model are available. Additional attributes
that are available are:

state_id
: The id of the state. This is the class property name that is given to the state.

state_name
: The name that is formed from the `state_id`. This is done by capitalizing the first letter and
replacing underscores by space characters.

chat_history
: This is a serialization of the complete dialogue history, formatted using
the `DialogueFormat.CHAT` format. (see XXX)

### conclusion
In the previous examples we have seen how, through `states`, `transitions`, `events`, `conditions`,
`actions` and `templates`, the programmer has complete control over how a dialogue flows and how
data is captured and presented along the way.

In the next chapter, we will go through these same three examples, but then with the actual 
Genie Flow code.

## Genie Flow Code Examples
### Question and Answer
The first, simple Question and Answer dialogue can be defined as follows:

```python
from statemachine import State

from ai_state_machine.genie_state_machine import GenieStateMachine
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.store import STORE


class QandAModel(GenieModel):

    @property
    def state_machine_class(self) -> type["GenieStateMachine"]:
        return QandAMachine


STORE.register_model(QandAModel)


class QandAMachine(GenieStateMachine):

    def __init__(self, model: QandAModel, new_session: bool = False):
        if not isinstance(model, QandAModel):
            raise TypeError("The type of model should be QandAModel, not {}".format(type(model)))

        super(QandAMachine, self).__init__(model=model, new_session=new_session)

    # STATES
    intro = State(initial=True, value=000)
    user_enters_query = State(value=100)
    ai_creates_response = State(value=200)

    # EVENTS AND TRANSITIONS
    user_input = intro.to(ai_creates_response) | user_enters_query.to(ai_creates_response)
    ai_extraction = ai_creates_response.to(user_enters_query)

    # TEMPLATES
    templates = dict(
        intro="q_and_a/intro.jinja2",
        user_enters_query="q_and_a/user_input.jinja2",
        ai_creates_response="q_and_a/ai_response.jinja2"
    )

```

#### data model
First, the `QandAModel` data model class is defined. Mark that this is a subclass of `GenieModel`
making sure that all the required properties are available and the newly created data model
can be persisted. This new data model class is in essence a pydantic model. All features of 
the pydantic framework can be used.

In this example there is not much happening as we are not extracting any data from the dialogue,
except for the dialogue itself - which is a standard feature of Genie Flow.

#### state machine - states
Secondly we defined the state machine class `QandAMachine`, which is a subclass of 
`GenieStateMachine` to ensure the base Genie Flow functionality is available. Within this class
we define our `states`, `transitions` and `templates`.

States are class properties, instantiated with a `State` object. This is the Python State Machine
object identifying a state machine state. Here we see the state `intro` getting the flag
`initial=True`, which identifies this state to be the initial state (of which there can only
be one). Since this example shows a never ending dialogue, there is no state with the predicate
`final=True`.

All states in this `QandAMachine` class have a unique `value`. This is a `str` or `int` that
uniquely identifies the state. These are defined by the developer and their value is
insignificant.

#### state machine - events and transitions 
We also define the transitions that are possible between states. This is done by assigning
transitions to the event that triggers them. So in this example, the event `user_input` will
make the machine transition to the state `ai_creates_response` when it is currently either in
the state `intro` or the state `user_enters_query`. Here the two transitions, `intro` to
`ai_creates_response` and `user_enters_query` to `ai_creates_response` are chained together using
the `|` character.

The event `ai_extraction` is defined to trigger the remaining transition of this state machine,
which is the transition between `ai_creates_respponse` to `user_enters_query`.

#### state machine - templates
And finally, we define the templates that are linked to each and every state. At initiation
of a new Genie Flow state machine, it is checked to see if all states have a template
assigned and will raise an exception if not all of them have one.

Templates are used to both render the output that needs to be sent to the user as well as the
prompt that needs to be sent to the LLM. They are Jinja2 templates, and are rendered with the
data that is captured so far. For example, the `intro` state has the following template:

```jinja2
Welcome to this simple Question and Answer dialogue Genie Flow example!

How can I help? Please go ahead and ask me anything.
```

This is the template that is sent to the user as a welcome message. When the user then enters
a query, a prompt is sent to the LLM. That prompt is constructed using the template that is 
linked to the state `ai_creates_response`:

```jinja2
You are a friendly chatbot, aiming to have a dialogue with a human user. You will be given
the dialogue that you have had before, followed by the most recent response from the user.
Your aim is to respond logically, taking the dialogue you had into account.

---
*** DIALOGUE SO FAR ***
{{ chat_history }}
---

---
*** MOST RECENT HUMAN STATEMENT ***
{{ actor_input }}
___

First assert if the most recent human statement indicated that the user wants to stop the dialog.
If the user wants to stop the dialogue, just say **STOP**.

If the user does not want to stop, respond.
Be succinct, to the point, but friendly.
Stick to the language that the user start their conversation in.
```

Here the power of Jinja2 comes to bear. The template contains "mustache notation" to indicate
the placeholders for data attributes. So will `{{ actor_input }}` be replaced by the most
recent statement by the most recent actor. Any attribute of the `QandAModel` is available
inside the template.

That makes the template for state `user_enters_query` straight forward:

```jinja2
{{ actor_input }}
```

Meaning that it just prints the output of the LLM. Because, when this template gets rendered,
the actor was the LLM and the attribute `actor_input` will be the output of the LLM.

### Question and Answer with Conditions
Putting conditions on transitions is straight forward. In the source code of 
[q_and_a_cond.py](../example_qa/q_and_a_cond.py) it can be seen that we introduced a state
`outro`, with an attribute `final=True`, which indicates this is a final state from which
no more transitions can be made.

There are also added conditions to some of the transitions, as can be seen from this snippet:

```python
    user_input = (
            intro.to(ai_creates_response) |
            user_enters_query.to(ai_creates_response, unless="user_says_stop") |
            user_enters_query.to(outro, cond="user_says_stop")
    )
```

Here, the event `user_input` will trigger a transition from state `intro` to `ai_creates_response`
without any condition. But the transition from `user_enters_query` will be only be towards
state `ai_creates_response` **unless** `user_says_stop` and towards the state `outro` under the
condition `user_says_stop`. In normal words: if the user says stop, we transition directly to
the `outro` state, otherwise we go to state `ai_creates_response`

These conditions are plain Python methods that we defined on our state machine class:

```python
from statemachine.event_data import EventData

from ai_state_machine.genie_state_machine import GenieStateMachine

class QandACondMachine(GenieStateMachine):

    ...

    def user_says_stop(self, event: EventData):
        return (
            event.args is not None and
            len(event.args) != 0 and
            event.args[0] == "*STOP*"
        )
```

> This method is called as the very first method when our state machine receives an event that
results in a transition with a condition. In the order of play, our Genie Flow code by then
has not yet had a chance to do anything, so we need to deal with the raw `EventData` object
that is passed by the Python State Machine framework.

This method just checks the data that is received with the event. The `EventData` class carries
a list of arguments that were passed when the event got sent. So it is checked to see if it is
not `None`, does not have zero length and if the first parameter has the value `*STOP*`. This
is the text that a user can enter to indicate they are done with the dialogue and want to stop.

The condition is linked to the transition by stating the name of the method, as can be seen from 
the above snippet. They can be stated "positively" (as in: this must be `True` to make the
transition), by making it a `cond` on the transition. They can also be stated negatively
(as in: this must be `False` to make the transition), by making it an `unless` condition.

### Question and Answer with data capture
The final Question and Answer example captures the username. This means we now want to capture
that name and be able to use it in our templates. Example code for this can be found in
[q_and_a_capture.py](../example_qa/q_and_a_capture.py).

#### data model
We now need to add the `user_name` as a property to our data model. It is the data attribute 
that we want to capture and carry across the dialogue.

```python
from typing import Optional

from pydantic import Field

from ai_state_machine.genie_model import GenieModel

class QandACaptureModel(GenieModel):
    user_name: Optional[str] = Field(None, description="The name of the user")

    ...
```

In true Pydantic style, we define the class property `user_name` to be an optional `str`, have a
default value of `None` and we give it a short description. This now means that our data model
has a property `user_name` that is persisted and available when templates get rendered.

#### data capture
We now also need to program the capturing of the data. In this example, the user enters their
name, which is then extracted using an LLM prompt. If the LLM cannot make out the name, the
user is asked again to state their name. This validation is done by commanding the LLM to respond
with a given token if it cannot make out a username, using the following LLM template:

```jinja2
You will be given a human response to the question "what is your name".
Your task is to extract the name of the user from that response.
If you can not determine that name, just respond with UNDEFINED.
If you can determine that name, just response with the name, nothing else.
```

This means we can define a condition as follows:

```python
    def name_is_defined(self, event: EventData) -> bool:
        return (
            event.args is not None and
            len(event.args) != 0 and
            event.args[0] != "UNDEFINED"
        )
```

But the main meal here is the definition of a method that gets called when the LLM _has_ extracted
the username. This is done by the following method on our `QandACaptureMachine` class:

```python
from ai_state_machine.genie_state_machine import GenieStateMachine

class QandACaptureMachine(GenieStateMachine):

    ...

    def on_exit_ai_extracts_name(self):
        self.model.user_name = self.model.actor_input

```
At the time the state `ai_extracts_name` is exited, the `actor_input` property of our data model
contains the value that is returned by the LLM. In the sunny day scenario, that contains the name
that is stated by the user. We therefore assign it to the data model property `user_name`.

Bear in mind that at this stage, we only know we are transitioning out of the `ai_extracts_name` state,
not if the username has been extracted. So we could be assigning the value `UNDEFINED` to
`model.user_name`.

> This method is called after the Genie Flow framework has had a chance to process information. So
we can refer to `model.actor_input`.
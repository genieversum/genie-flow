# Genie Flow State Transitions

## Event Flow
Transitioning from one state to another goes through the following steps:

1. The input that was sent with the event that triggered the transition is set as `actor_input`
2. The template for the target state is retrieved and assigned to the machine's `current_template`
   property.
3. If that template needs an Invoker:
   - if we are transitioning out of another invoker state, then we do not need to record the
     `actor_input` in the model dialogue. But if the current transition was user-triggered
     then the `actor_input` is added as "user" uttering.
   - after this transition, we are expecting a trigger from the invoker, rather than from the user
   - the actor is set to "assistant" - this is the actor that is currently active
   - the invocation is enqueued:
     - a (Celery) DAG of tasks is started
     - a `GenieTaskProgress` object is registered for this session (this contains the number
       of tasks to execute as well as a continuously updated total of executed tasks)
     - the final task of the DAG will be to send the next event back to the state machine
   - rendering of the target template is done as part of the enqueued task / set of tasks
   - because there is now an active Celery task, the API will send only the "poll" event as a
     possible next action
   - if a user triggered this transition, then they will gets sent the most recent addition to
     the dialogue, which is the actor input that was sent to trigger this transition
4. If that template does not need an Invoker, then it just needs to render the template
   and return the results.
   - we are now expecting the user to trigger a transition into the next state
   - we render the template of the target (the `actor_input` property contains the raw output
     of the previous state) 
   - we add the rendered output onto the dialogue and record it
   - the actor is set to "user" - this is the actor that is currently active and should send
     the next event

### output
When user sends an event (including the "poll" event) to the API, the API will respond with either:
* a list of next actions containing only "poll"
* the output of the previous state, rendered into the template of the new state and a list of 
  next actions (events) that can be sent.

## Task Progress 
Next possible actions will only be "poll" when there is an active Celery DAG running for the
session. This is done internally by checking if a progress object exists for that session.

This progress object contains the total number of tasks as well as the total number of executed
tasks. This information could be used by a user interface to indicate task progress.

### task-finish indication
When a Celery task is finished (the invoker DAG has concluded), the progress object is removed.
When we do an Invoker to Invoker transition, a new task DAG will be created for the second
Invoker, and consequently a new progress object is created. This meas that there is a short
period in time where there is no progress object for a session, but there is also nothing
else that the user needs to do, other than "poll".

Since the removal of the old progress object and the creation of the new one is done within
the same model object lock, the API will not be able to see that intermediate state and falsely
conclude that there is no active task. When the API comes along for a "poll" it will wait till
all the activity is done (wait for the lock to be released) after which it will conclude that
there is an active task and suggest another "poll" event.

### false update of percentage done
This situation will also impact the "total nr of tasks" and "total nr executed tasks" reporting
that happens when the user polls. These numbers will only refer to the number of tasks that
are in the currently executing DAG. Automatically jumping to a new DAG will reset to a new number
of tasks and set the number of executed tasks to zero. If these numbers are used for feedback
to the user, this would be unexpected.

> This may be something to fix when we start using these numbers for user feedback.

## Dialogue (a.k.a. Chat History)
The model object contains a list of utterings of the different parties involved in the dialogue.
This alternates between "assistant" and "user". The first for output from an invoker, the
second for output sent through the API.

When strictly alternating between Invoker and User, then we expect this dialogue list to
contain the alternating utterings, starting with "assistant", followed by "user", then back
to "assistant", etc.

But exceptions exist. With the wqy the task flow is constructed, we could have user to user
or invoker to invoker transitions.

Another issue is when a user sends "technical" information, such as a file binary or control
element (buttons, drop-downs, etc) results. We may not want to record these - or maybe record
a derivative of them.

### what gets stored
When the transition is triggered from the API (so that is a user input), the string that accompanied
that event is stored verbatim. This means that, all user input is stored inside the chat
history, without interference.

When the transition is triggered by a Celery DAG, the output of that DAG (typically an Invoker)
is first used to render the template that is connected to the target state. This is the information
that is going to be sent back to the user, so that is also what is stored as part of the dialogue.

### Invoker to Invoker transitions
When passing from one Invoker to the next Invoker, the output of the first invoker is passed on
to the next invoker as `actor_input` but the default pattern is to NOT store this intermediate
result as part of the dialogue. It is assumed that this intermediate result is technical in
nature and should not feature as part of the chat history. Only the last Invoker of a sequence
like this, before control is handed back to the User, is stored. And since this is an Invoker
output, it is used to render the template of the target state and the result of that is stored
as part of the dialogue.

### User to User transition
In case a transition is made from a user state onto the next user state, this is assumed to be
important for the dialogue. Hence, the default is to store the `actor_input` into the dialogue.

## Advanced
The above should give you enough to start building Genie Agents. This chapter exists for when
you want further details on how the internals of Genie Flow work and want to use that information
to further enhance you flows.

### transition steps
To fully understand how the transition from one state to another is managed, one needs to
understand the following sequence. This sequence shows in what order the different "hooks" on
a state machine are being called during a transition. For [more information, please refer to
the original documentation](https://python-statemachine.readthedocs.io/en/latest/actions.html#ordering).

The following groups of methods are called in sequence (if they exist). **Note: Within the group
the order of calling is not defined (and could be in parallel)**.

| Group               | Hooks used by Genie   | Transition Hooks  | Event Hooks          | State Hooks                                      | Current state |
|---------------------|-----------------------|-------------------|----------------------|--------------------------------------------------|---------------|
| Validators          |                       |                   | `validators()`       |                                                  | `source`      |
| Conditions          |                       |                   | `cond()`, `unless()` |                                                  | `source`      |
| Before              | `before_transition()` |                   | `before_<event>()`   |                                                  | `source`      |
| Exit                |                       |                   |                      | `on_exit_state()`,<br/> `on_exit_<state.id>()`   | `source`      |
| On                  |                       | `on_transition()` | `on_<event>()`       |                                                  | `source`      |
| **STATE UPDATE**    |                       |                   |                      |                                                  |               |
| Enter               |                       |                   |                      | `on_enter_state()`,<br/> `on_enter_<state.id>()` | `destination` |
| After               | `after_transition()`  |                   | `after_<event>()`    |                                                  | `destination` |

The state machine package makes the machine go through each of these groups and checks if there
exist any of these hooks and calls them.

#### Genie Flow Hooks
In order to manage the Genie internals, the following hooks are implemented:

`before_transition()`
: this hook determines how the transition will be conducted. It will set the property
`transition_type` to a tuple containing the source type and the destination type. A type can
be either "invoker" or "user". So, for example, the tuple `("invoker", "user")` means that
the source state was an invoker state and the target a user state.
This hook also sets the `actor`, based on the type of the source state. The actor is either
"assistant" (source state was invoker type) or "user" (source state was user type).
And, finally, this hook determines if and how the event argument should be stored as part of
the dialogue. The property `dialogue_persistance` is set to "NONE", "RAW" or "RENDERED".

`after_transition()`
: this hook is used to trigger the Celery task, if the target state is an "invoker" state.
This hook also checks the `dialogue_persistence` property and determines if and what gets added
to the dialogue.

#### Genie Flow standard behaviour
The following standard behaviour drives how Genie Flow conducts it's logic:

| `transition_type`  | `agent`   | `dialogue_persistence` | Celery DAG |
|--------------------|-----------|------------------------|------------|
| user -> user       | user      | RENDERED               | no         |
| user -> invoker    | user      | RAW                    | yes        |
| invoker -> user    | assistant | RENDERED               | no         |
| invoker -> invoker | assistant | NONE                   | yes        |

#### deviating from the default
Although the general rules are sensible, and should cater to most of the use cases, one might
want to deviate from this pattern. The most obvious change is to change the `dialogue_persistence`
property. This will then influence how `actor_input` is stored as part of the dialogue.

Whatever hook is used by the Agenteer does not really matter. Since this property is set right
at the start of the transition (on the `before_transition()` hook), any hook after that (but
before the `after_transition()` hook) would work.

And, because these alterations make most sense for a specific transition rather than generically,
for all transitions, we suggest using the `on_enter_<state.id>()` hook. Just in time for the
`after_transition()` hook.
# Genieversum
## Our Mission
Genie Flow (or simply Genie) is a modular AI platform designed to help you build intelligent, 
reusable agents that can automate tasks, process data, and interact with users or systems. 
Whether you're a seasoned developer or just starting out, Genie Flow offers a flexible and 
approachable way to create smart workflows.

Our vision is that a _good_ agentic framework should be:

* **Code First** – We do not have a "low code" environment. We believe in the power of 
  expression of well-written code.
* **Deployable** – A Genie agent is ready to deploy as an API. There is no magic engine or 
  deployment formula. Your agent is built into a Docker container and comes with a well-documented 
  API out of the box.
* **Scalable** – Work is queued to be picked up by workers. This makes your agent immediately 
  scalable. From your laptop to large server clusters. One code base. Scalable out of the box.
* **Community Driven** – AI should be available for everyone, and everyone should be able to
  contribute.

We do consulting. We are not a software house. We are not a product company. We are not a 
service or hosting provider. We make our living by helping large organisations to make the 
best use of AI. We are the company where Next is Made Real.

## What is Genie
Simply put: Genie is an agentic AI orchestrator. It manages the dialogue between an actor 
(human or machine) and a cascade of calls to external systems. Many of these external systems 
may be Large Language Models, but the dialogue flow typically combines that with other sources 
of information and operational systems that can be reached via an API.

### Example Genie Agent
Imagine the following use case:

> As a user, I want to have a dialogue with a Large Language Model.

Three steps:

1. Create your data model
2. Define how you want the dialogue to flow
3. Specify the templates to use in each of the steps

#### Defining your data model
First, you define your `GenieModel` - a Pydantic data model of information that you want to 
carry during the dialogue session.

```python
class MyFirstModel(GenieModel):

    # there are no specific data elements I need to carry

    # link this model to the state machine
    @classmethod
	def get_state_machine_class(cls) -> type[GenieStateMachine]:
        return GenieStateMachine
```

#### Define the flow of your dialogue
Next, you define how your dialogue needs to flow by creating your dialogue's state machine:

```python
class MyFirstMachine(GenieStateMachine):
    
    # STATES
    into = State(initial=True, value=100)
    ai_creates_response = State(value=200)
    user_enters_query = State(value=300)

    # EVENTS & TRANSITIONS
	user_input = (
        intro.to(ai_creates_response)
        | user_enters_query.to(ai_creates_response)
    )
    ai_extraction = (
        ai_creates_response.to(user_enters_query)
    )

    # TEMPLATES
    templates = dict(
        intro="response/intro.jinja2",
        ai_creates_response="llm/ai_creates_response.jinja2",
        user_enters_query="response/user_enters_query.jinja2",
    )
```

This creates a dialogue that looks like:

```mermaid
stateDiagram-v2
	direction LR
	[*] --> intro
	intro --> ai_creates_response: user_input
	ai_creates_response --> user_enters_query: processing_done
    user_enters_query --> ai_creates_response: user_input
	
    intro: Intro
	ai_creates_response: AI Creates Response
    user_enters_query: User Enters Query
```

The most basic dialogue flow:

1. The Agent introduces themselves and asks a question
2. The user sends their input
3. An LLM formulates a response
4. The engine signals that processing is done
5. The user views the response and sends new input
6. Back to point 3

#### Creating the templates
We just need to define the templates. First template, the `intro.jinja2` template:

``` title="intro.jinja2"
Welcome to this simple Question and Answer dialogue Genie Flow example!

How can I help? Please go ahead and ask me anything.
```

We also need to define the prompt that will get sent to the LLM. This happens in the file 
`ai_creates_response.jinja2`:

```yaml title="ai_creates_response.jinja2"
- role: system
  content: |
    You are a friendly chatbot, aiming to have a dialogue with a human user.
    Your aim is to respond logically, taking the dialogue you had into account.
    Be succinct, to the point, but friendly.
    Stick to the language that the user start their conversation in.

{{ chat_history }}

- role: user
  content: |
{{ actor_input|indent(width=4, first=True) }}
```

This template defines the `system` prompt, followed by the `{chat_history}`, followed by the 
input from the previous actor. That will be the human user in our case.

And then, the final template, `user_enters_query.jinja2`:
``` title="user_enters_query.jinja2"
{{ actor_input }}
```
Here, the user is presented with the response from the previous actor (the LLM in this case).

#### Switch on
That's it! This defines a fully fledged AI agent.

Deploying this would mean: create a `main.py` that tells Genie where your and data model class 
live, run the worker, run the API and spin up a front-end that talks to your API. We have 
provided a simple command-line interface that we use in anger during development, and a simple 
React chat interface that you can get started with.

## Where from here?

- [Documentation](https://genieversum.github.io) for in-depth documentation of the framework.
- [Getting Started](https://genieversum.github.io/getting_started/) for a step-by-step guide to run the above example.
- [Under the Hood](https://genieversum.github.io/under_the_hood/under_the_hood/) for a detailed description of the underlying architecture.
- [Contribute](https://genieversum.github.io/community/contributing/)
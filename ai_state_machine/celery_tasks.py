import os

from celery import Celery
import openai
from jinja2 import Template
from openai.types.chat.completion_create_params import ResponseFormat

from ai_state_machine.model import CompositeContentType
from ai_state_machine.store import store_model, retrieve_model, get_lock_for_session, \
    get_class_from_fully_qualified_name

app = Celery(
    "My Little AI App",
    backend="redis://localhost",
    broker="pyamqp://",
)


_OPENAI_CLIENT = openai.AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
)
deployment_name = 'SOME DEPLOYMENT NAME'


@app.task
def trigger_ai_event(response: str, cls_fqn: str, session_id: str, event_name: str):
    with get_lock_for_session(session_id):
        model = retrieve_model(cls_fqn, session_id=session_id)
        model.running_task_id = None

        state_machine = model.create_state_machine()
        state_machine.send(event_name, response)

        store_model(model)


@app.task
def call_llm_api(prompt: str) -> str:
    response_format = ResponseFormat(type="json_object") if "JSON" in prompt else None
    response = _OPENAI_CLIENT.chat.completions.create(
        model=deployment_name,
        messages=[
            # {"role": "system", "content": json_instructions},
            {"role": "user", "content": prompt}
        ],
        response_format=response_format,
    )

    try:
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error: {e}")
        return f"** call to OpenAI API failed; error: {str(e)}"


@app.task
def combine_group_to_dict(
        results: list[CompositeContentType],
        keys: list[str]
) -> CompositeContentType:
    return {
        keys[i]: results[i]
        for i in range(len(keys))
    }


@app.task
def chained_template(
        result_of_previous_call: CompositeContentType,
        template_content: str,
        model_class_fqn: str,
        session_id: str,
) -> CompositeContentType:
    with get_lock_for_session(session_id):
        model = retrieve_model(model_class_fqn, session_id=session_id)

    render_data = model.model_dump()
    render_data["previous_result"] = result_of_previous_call
    template = Template(template_content)
    return template.render(render_data)

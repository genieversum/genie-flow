import logging
import os

from celery import Celery
import openai
from openai.types.chat.completion_create_params import ResponseFormat

from ai_state_machine.model import CompositeContentType
from ai_state_machine.store import store_model, retrieve_model, get_lock_for_session
from ai_state_machine.templates import ENVIRONMENT

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
def call_llm_api(
        template_name: str,
        render_data: dict[str, str],
) -> str:
    template = ENVIRONMENT.get_template(template_name)
    prompt = template.render(render_data)

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
        logging.warning(f"Failed to call OpenAI: {str(e)}")
        return f"** call to OpenAI API failed; error: {str(e)}"


@app.task
def combine_group_to_dict(
        results: list[CompositeContentType],
        keys: list[str]
) -> CompositeContentType:
    return dict(zip(keys, results))


@app.task
def chained_template(
        result_of_previous_call: CompositeContentType,
        template_name: str,
        render_data: dict[str, str],
) -> CompositeContentType:
    render_data["previous_result"] = result_of_previous_call
    return template_name, render_data

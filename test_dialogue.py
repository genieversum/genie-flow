import time

import requests

HOST = "http://127.0.0.1:8000"
BASE_URL = HOST + "/v1/ai/claims_genie"

response = requests.get(f"{BASE_URL}/start_session")
ai_response = response.json()
session_id = ai_response["session_id"]

while True:
    if ai_response["error"]:
        print("===")
        print(ai_response["error"])
        print("===")
        break

    if ai_response["response"]:
        print("\n---")
        print(ai_response["response"])

    if "user_input" in ai_response["next_actions"]:
        user_input = input("\n >> ")
        event = dict(
            session_id=session_id,
            event="user_input",
            event_input=user_input,
        )

    elif "poll" in ai_response["next_actions"]:
        time.sleep(1)
        print(".", end="", flush=True)
        event = dict(
            session_id=session_id,
            event="poll",
            event_input="",
        )

    elif "advance" in ai_response["next_actions"]:
        event = dict(
            session_id=session_id,
            event="advance",
            event_input="",
        )

    elif len(ai_response["next_actions"]) == 0:
        print("***")
        break

    else:
        print("BOOP")
        break

    # print(">>", json.dumps(event))
    response = requests.post(f"{BASE_URL}/event", json=event)
    response.raise_for_status()
    ai_response = response.json()
    # print("<<", json.dumps(ai_response))

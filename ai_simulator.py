def extract_activity_type(user_input: str) -> str:
    if "leak" in user_input.lower():
        return "leak"
    return "paint"


def extract_activity_type_verification(user_input: str) -> str:
    if "yes" in user_input.lower():
        return "YES"
    if "no" in user_input.lower():
        return " ".join(user_input.split((" "))[1:])
    return "NOT_PROVIDED"


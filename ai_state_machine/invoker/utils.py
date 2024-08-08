import os


def get_config_value(
    config,
    env_variable_name: str,
    config_variable_name: str,
    variable_name: str,
    default_value: str | bool | int | None = None
) -> str | bool | int | float | None:
    result = os.getenv(env_variable_name)
    result = result or config.get(config_variable_name, None)
    if result is None:
        return default_value
    return result

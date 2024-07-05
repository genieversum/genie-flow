import os


def get_config_value(config,
                     env_variable_name: str,
                     config_variable_name: str,
                     variable_name: str,
                     ) -> str | bool | int | float:
    result = os.getenv(env_variable_name)
    result = result or config.get(config_variable_name, None)
    if result is None:
        raise ValueError(f"No value for {variable_name}")
    return result
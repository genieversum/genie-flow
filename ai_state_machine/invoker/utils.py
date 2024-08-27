import os


ConfigVariableType = bool | int | str | None

def get_config_value(
    config,
    env_variable_name: str,
    config_variable_name: str,
    variable_name: str,
    default_value: ConfigVariableType = None
) -> ConfigVariableType:
    result = os.getenv(env_variable_name)
    result = result or config.get(config_variable_name, None)
    if result is None:
        return default_value
    return result


class ConfigReader:
    def __init__(
            self,
            config: dict,
            environment_prefix: str,
    ):
        self.environment_prefix = environment_prefix.upper()
        self.config = config

    def get_config_value(
            self,
            config_variable_name: str,
            default: ConfigVariableType = None,
    ) -> ConfigVariableType:
        env_variable_name = f"{self.environment_prefix}_{config_variable_name.upper()}"
        return get_config_value(
            self.config,
            env_variable_name=env_variable_name,
            config_variable_name=config_variable_name,
            variable_name=config_variable_name.replace("_", " "),
            default_value=default,
        )

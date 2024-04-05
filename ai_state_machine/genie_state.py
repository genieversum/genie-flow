from jinja2 import Template
from statemachine import State


class GenieState(State):

    def __init__(self, value: str | int, template: str | Template, **kwargs):
        if not isinstance(value, str) and not isinstance(value, int):
            raise ValueError("`value` must be of type str or int and not {}".format(type(value)))

        super().__init__(value=value, **kwargs)
        self.template = template

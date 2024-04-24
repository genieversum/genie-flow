from jinja2 import Environment, FileSystemLoader

ENVIRONMENT = Environment(
    loader=FileSystemLoader('example_claims/templates'),
    autoescape=False,
)

from jinja2 import PackageLoader, Environment

ENVIRONMENT = Environment(
    loader=PackageLoader('ai_state_machine', 'example_claims'),
    autoescape=False,
)


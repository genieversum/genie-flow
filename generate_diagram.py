import argparse

from pydantic._internal._model_construction import ModelMetaclass
from statemachine.contrib.diagram import DotGraphMachine

from ai_state_machine.genie import GenieModel
from ai_state_machine.store import get_class_from_fully_qualified_name

parser = argparse.ArgumentParser(
    prog="generate_diagram.py",
    description="Generate the state machine diagram for a Genie Model class",
)
parser.add_argument(
    "class_fqn",
    metavar="class_fqn",
    type=str,
    help="the fully qualified name of the model class",
)
args = parser.parse_args()

model_cls = get_class_from_fully_qualified_name(args.class_fqn)
assert isinstance(model_cls, ModelMetaclass), "Must pass FQN of a GenieModel subclass"

model: GenieModel = model_cls(session_id="just for the plot")
machine = model.get_state_machine_class()(model=model)
graph = DotGraphMachine(machine)
dot = graph()
dot.write_png(f"{args.class_fqn}.png")

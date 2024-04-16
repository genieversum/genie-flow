from statemachine.contrib.diagram import DotGraphMachine

from example_claims.claims import ClaimsModel

model = ClaimsModel(session_id="just-a-plot")
machine = model.create_state_machine()
graph = DotGraphMachine(machine)
dot = graph()
dot.write_png("claims-state-machine.png")

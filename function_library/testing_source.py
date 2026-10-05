"""An ordinary reasoning source that chooses experiments through the shared service."""

from .reasoning import ReasoningSource, SYSTEM_PROMPT
from .reasoning_transport import exchange
from .testing import experiment_request


GUIDANCE = (
    "Design an experiment or inspect prior experimental evidence to advance the goal. "
    "The Target Workflow is the scoped Episode workflow under test; candidate_ref selects an exact candidate revision. "
    "The IterativeEpisodeRefiner works on that workflow. Testing the refiner itself requires explicit refinement scope. "
    "Choose action_class from the frozen allowed actions. action_inputs must be the exact "
    "payload for that experiment operation in testing_service.worker_payload_schemas. "
    "The experiment specifies your question, rationale, expected and falsifying outcomes, scope and mode. "
    "Use inventory to inspect exact recorded invocation paths, unit identities and available entry context; it does not grant replay or checkpoint authority. "
    "Use history to discover past tests, measured outcomes, and saved recordings before "
    "choosing reuse. A reuse lead is not permission or proof of compatibility. "
    "Assigned criteria are fixed, not your predictions. Preview when scope "
    "or compatibility is uncertain; use run when the design is ready. Choose follow-ups "
    "from observed evidence, unresolved questions and limitations, not a fixed sequence. "
    "Use continue only with an exact interrupted reference returned by status or history, "
    "to resume the same experiment; changed code, inputs or criteria require a new experiment. "
    "A continuation lead still requires host validation and current execution authority. "
    "Only findings copied exactly from host experiment_measurement evidence can be admitted. "
    "For such an entity, fields.measurement is the JSON-encoded complete body.observation. "
    "Keep candidate_lessons and revisions empty. An observed candidate failure can resolve "
    "a requirement; an execution error or unmeasured result does not. Repeated findings "
    "receive no new credit. Never decide completion or grant parent acceptance."
)


class TestingSource(ReasoningSource):
    system_prompt = SYSTEM_PROMPT + " " + GUIDANCE
    selection_prompt = ReasoningSource.selection_prompt + " " + GUIDANCE

    def __init__(self, goal, *, selection_model_type, execution_model_type):
        super().__init__(
            goal,
            selection_model_type=selection_model_type,
            execution_model_type=execution_model_type,
        )
        self.last_experiment = None

    async def _select(self, bundle):
        description = await experiment_request(operation="describe", payload={})
        return await super()._select({
            **bundle,
            "testing_instructions": GUIDANCE,
            "testing_service": description,
            "previous_experiment": self.last_experiment,
        })

    async def _action_input(self, typed_input, selection):
        from .testing_contract import validate_operation_payload

        operation = selection["action_class"]
        validate_operation_payload(operation, selection["action_inputs"])
        self.last_experiment = await experiment_request(
            operation=operation, payload=selection["action_inputs"]
        )
        # Retrieval now includes host evidence from the just-committed response.
        # It changes unit data, never the cached system prompt or the contract.
        refreshed = await exchange("retrieve", {})
        return {
            **{
                key: value
                for key, value in refreshed.items()
                if key != "pending_submission"
            },
            "experiment_response": self.last_experiment,
        }


def open_testing_source(goal, *, selection_model_type, execution_model_type):
    return TestingSource(
        goal,
        selection_model_type=selection_model_type,
        execution_model_type=execution_model_type,
    )

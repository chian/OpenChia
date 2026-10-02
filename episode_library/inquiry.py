"""Problem-discovery configuration of the generic reasoning Episode."""

from dataclasses import replace

from function_library.epistemic import default_components
from function_library.epistemic_contract import EpistemicContract, INQUIRY_ACTIONS
from .models import EpisodeLibraryDesign
from .reasoning import BINDING as GENERIC_BINDING, DESIGN as GENERIC_DESIGN


def inquiry_contract(
    *, goal_class, domain, environment, evidence=(), scope_tier="episode"
):
    return EpistemicContract(
        goal_class=goal_class,
        domain=domain,
        allowed_actions=INQUIRY_ACTIONS,
        environment=environment,
        assumptions=(),
        required_fields=(
            "statement",
            "defined_terms",
            "scope",
            "boundary_conditions",
            "claimed_unknown",
            "why_it_matters",
            "prior_art_separation",
        ),
        required_evidence=("support", "counterevidence", "prior_art"),
        components=default_components(),
        scope_tier=scope_tier,
        evidence=evidence,
    )


BINDING = replace(
    GENERIC_BINDING,
    grain_name="inquiry",
    interface="reasoning.inquiry",
    goal="Discover well-formulated open problems with explicit evidence, counterevidence and answer contracts.",
)
DESIGN = EpisodeLibraryDesign(
    qualified_name="reasoning.inquiry",
    title="Open-problem inquiry",
    binding=BINDING,
    function_definitions=GENERIC_DESIGN.function_definitions,
    source_symbols=(),
)

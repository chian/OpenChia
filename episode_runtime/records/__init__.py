"""Shared records for execution, experiments and replay.

``runs``/``facts`` define compact typed facts; ``index`` maintains them atomically
in RunStore and ``inventory`` queries exact invocation/unit prefixes;
``experiments`` owns immutable experiment records in DuetStore. Audit evidence
stays in its existing store and is loaded only for explicit verification.
"""

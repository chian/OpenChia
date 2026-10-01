# Duet-owned Episode design

The Duet is the human and conversational LLM working together. It owns the
workflow architecture and persists complete workflow revisions. The Duet is
not an Episode and does not execute task work.

Each workflow node is a task-specific Episode with a goal, repeatable unit,
result, numeric progress measure, stopping rule, capabilities, and deliverable
boundary. The topology is complete before launch. During execution, child
Episodes return closed results containing only their declared identity,
artifact, numerical, state, and flag projections.

The host validates each revision against its capability ceiling and freezes
the exact human-approved workflow. EpisodeBuilder must then materialize and
validate task-specific Episode modules before anything can launch. Search is
available to the conversational half of the Duet as read-only information
gathering. Search results do not grant authority.

Rarefaction is the numerical continuation mechanism. It measures yield from
accepted identities, estimates the value of another unit, and closes an
Episode when its registered numerical rule says the acquisition is exhausted.
Parent Episodes receive typed child outcomes as observations on their own
scale.

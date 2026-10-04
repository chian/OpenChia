"""Bind ordinary human Run requests to the shared execution service."""

from function_library.epistemic_contract import exact


def record_launch_intent(artifacts, registration, launch_id, configuration_hash):
    from ..records.experiments import put_data

    return put_data(
        artifacts,
        registration.duet_id.value,
        "launch_intent",
        {
            "registration_hash": registration.registration_hash.value,
            "model_launch_id": launch_id,
            "configuration_hash": configuration_hash,
        },
    )


def validate_launch_intent(artifacts, registration, intent):
    record = exact(
        intent,
        {"registration_hash", "model_launch_id", "configuration_hash"},
        "ordinary Run launch intent",
    )
    if record["registration_hash"] != registration.registration_hash.value:
        raise ValueError("launch intent binds another Run registration")
    launches = [
        event["record"]
        for event in artifacts.events(registration.duet_id.value)
        if event["event_type"] == "model_launch_resolved"
        and event["record"]["launch_id"] == record["model_launch_id"]
    ]
    if len(launches) != 1 or any(
        launches[0][key] != expected
        for key, expected in (
            ("kind", "run"),
            ("subject_id", registration.run_id.value),
            ("configuration_hash", record["configuration_hash"]),
        )
    ):
        raise ValueError("launch intent lacks its exact resolved model configuration")

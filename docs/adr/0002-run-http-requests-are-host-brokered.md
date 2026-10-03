# ADR 0002: Run HTTP requests are host-brokered

Status: Accepted

Implementation: implemented in chian/OpenChia#11 (closes #8).

Related: [ADR 0005](0005-target-workflow-runs-use-containers.md) selects containers
as the default for Target Workflow Runs on Linux and macOS. It preserves this
record's host-brokered requests and host-only credentials.

## Context

An Episode Run executes in a worker with no network. The systemd backend sets `PrivateNetwork=yes`, the container backend passes `--network none`, and the worker's seccomp filter denies `socket` and `connect`. The only channel out of the sandbox is the stdin/stdout frame pipe to the host.

Today only model calls cross that pipe. `ScopedModelBroker` (`episode_runtime/broker.py`) admits each `model_request`, performs it on the host, and records request and response hashes in the Run evidence chain.

That default is correct, but it makes a class of workflows impossible. The first real workflow designed with OpenChia, the BV-BRC RAGstack `asm-next` parameter and structure study, needs hundreds of read-only HTTP calls per collection to `https://www.bv-brc.org/ragstack/asm-next/api/`. Its approved contract called for an allowlisted read-only HTTP client inside the Run. Under the sandbox that client receives `EPERM` on its first `socket()`, the Run fails at its first unit, and no measurement can be produced.

## Decision

A Run reaches an external HTTP service only through a second brokered request kind, `http_request`, that mirrors the model path one-for-one. Every existing invariant holds: there is no unmediated egress, authority comes only from the approved workflow, the credential never enters the sandbox, and every exchange is hashed into the Run evidence.

The allowlist is part of the approved contract (D1). `EpisodeCreationSpec` gains `egress_allowlist`, a tuple of `EpisodeEgressRule`, empty by default. It is included in `spec_hash` and therefore in the approved `workflow_hash`. The Duet proposes the rules when a workflow calls an external API; the human approves them with the rest of the Architecture; the Run cannot add or widen one.

Only read-only use is admitted, and `effect_mode` is unchanged (D2). `RuntimePolicy.effect_mode` stays `no_effects`. Each rule must declare `read_only: true` and may admit only `GET`, `HEAD` and `POST`. `POST` is admitted only because the approving human asserts that the endpoint is a read-only query. Any other method, or a rule without `read_only: true`, is a contract validation error. The broker enforces the same constraint again at request time.

The approved rules travel in the Run registration (D3). `RunRegistration.egress_policy` maps each node `local_id` to its rule records. It is part of `semantic_record`, so it is hashed into the registration and the worker receives it in `INITIALIZE`. It contains no secrets.

The operator sets a ceiling and supplies credentials by name (D4). Host configuration `openchia.egress` lists `allowed_hosts` (exact lowercase hostnames) and named `credentials` (`kind: bearer_token_file`, `path`, `header` defaulting to `Authorization`, `scheme` defaulting to `Bearer`). `WorkflowAdmissionAuthority` carries `egress_hosts` and `egress_credential_names` as sorted tuples, hashed into the authority. Duet validation rejects a rule whose host or credential lies outside that ceiling with the deficits `egress_host_not_allowed`, `egress_credential_unknown` or `egress_rule_invalid`. A rule refers to a credential by name; the host reads the token file at request time and adds the header itself.

Failures are typed responses, not Run failures (D5). The broker always returns a response record whose `outcome` is `ok`, `denied`, `transport_error` or `oversize`. The Episode decides what a failed request means for its unit of work. Only protocol violations fail the Run: a malformed frame, an unknown request id, or an `episode_path` that does not hash to the claimed `episode_id`.

The host recomputes attribution (D6). The worker sends both `episode_id` and `episode_path`. The host recomputes `EpisodeRef(run_id, path).episode_id`, requires equality, and takes the grain name of the last path element as the node `local_id` whose rules apply. The worker cannot borrow another node's allowlist by naming it.

Budgets are isolation bounds, not stopping rules (D7). `max_requests` counts per `(local_id, rule)` per Run; a request over budget receives `denied`. `max_response_bytes` must not exceed `max_frame_bytes` minus 131072 bytes of frame overhead (917504 bytes for a 1 MiB frame); a larger response receives `oversize`. A workflow's own stopping rules remain in the workflow.

Redirects are not followed (D8). The host transport uses `follow_redirects=False`. A 3xx response is returned with its status and filtered headers, including `location`, and no body.

Hashes exclude credentials (D9). `request_hash` covers the admitted worker request record, before the host adds the credential header. `response_hash` covers the response record returned to the worker.

### Records

| Record | Direction | Shape |
| --- | --- | --- |
| `EpisodeEgressRule` | contract | `name` (unique token), `host` (lowercase, no scheme or port), `path_prefix` (absolute, normalized), `methods` (sorted subset of `GET`/`HEAD`/`POST`), `read_only` (must be `true`), `max_requests` (≥ 1), `max_response_bytes` (1 to 917504), `credential` (name or `null`). `https://` is implied. |
| `RunRegistration.egress_policy` | host → worker (`INITIALIZE`) | `{local_id: [rule, ...]}`, sorted by key; nodes without rules are omitted. |
| `http_request` frame | worker → host | `{http_request_id, episode_id, episode_path, request}`; `episode_path` is root→leaf `{grain, key}` entries. |
| HTTP request record | inside the frame | `method`, `url`, `headers` (lowercase; `authorization`, `cookie`, `proxy-authorization`, `host`, `content-length`, `transfer-encoding` forbidden), `body` (`null` or UTF-8 text, `POST` only), `timeout` (`null` or 0 < t ≤ 120). |
| `http_response` frame | host → worker | `{http_request_id, response}`. |
| HTTP response record | inside the frame | `outcome`, `status`, `headers` (only `content-type`, `content-length`, `date`, `retry-after`, `x-request-id`, `location`), `body`, `body_encoding` (`utf-8` or `base64`), `reason`, `rule`. |
| `HTTP_REQUESTED` event | worker origin | `{http_request_id, request_hash, rule, method, host, path}`; `path` excludes the query. |
| `HTTP_RESPONDED` event | host origin | `{http_request_id, request_hash, response_hash, outcome, status, response_bytes, rule}`. |

`http_request_id` is a content id over `run_id`, `registration_hash`, `episode_id`, a per-Run HTTP ordinal and `request_hash`, using the same scheme as model requests with a separate counter. Neither event kind is worker-emittable. Generated Episode code calls the stdlib-only `http_call_library` (`http.request`, `http.json`), which reaches the broker only through the worker's frame transport and fails closed when no transport scope is set.

## Consequences

- Workflows whose unit of work is a read-only call to an external service, including the RAGstack study, can run without opening the sandbox network.
- Every external exchange is host-observed. The audit log proves which rule admitted each request and what came back, exactly as it does for model calls.
- Egress authority has two independent gates: the operator's ceiling in host configuration and the human-approved contract. Changing either requires an explicit act outside the Run.
- Secrets stay on the host. They never appear in a frame, an event payload, a hash input or a log line. This is stricter than the RAGstack contract's original plan to open the token inside the Run.
- Adding a rule changes `spec_hash` and `workflow_hash`, so an existing approval does not silently gain egress.

The following remain out of scope:

- Requests with external effects. Anything beyond read-only use would need a new `effect_mode` that the human approves explicitly; this decision does not create one.
- Redirects. A workflow that needs a redirected resource must allowlist its final location and request it directly.
- Streaming or chunked bodies larger than one frame. A response above `max_response_bytes` is reported as `oversize`, not delivered in parts.
- Plain `http://`, non-default ports and wildcard hosts.

## Alternatives considered

### Open the network for allowlisted hosts

Rejected. Allowing egress through systemd `IPAddressAllow` or a Docker egress proxy, as `tools/environments/docker_egress.py` does for the terminal sandbox, would be simpler. But the Run's calls would leave the evidence chain, the token would have to live inside the sandbox, and seccomp's `socket` denial would have to be loosened. The evidence principle requires every external interaction to be host-observed and hashed.

### Pre-fetch responses on the host before the Run

Rejected. Pre-fetching works only when the complete query set is known in advance. A parameter sweep that adapts to its own results, such as noise-floor gating or rerank decisions, cannot be pre-fetched.

## Implementation status

In progress on branch `feat/http-broker`. The contract chain (`EpisodeEgressRule`, authority ceilings, Duet deficits, `RunRegistration.egress_policy`, event kinds), the protocol frames, worker transport, staged `http_contracts` and `http_call_library`, and the host broker with executor and host wiring are being implemented as separate tasks. This record will be updated when the branch lands.

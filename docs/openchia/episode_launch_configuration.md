# Episode launch configuration

Select the project and model routes for target Builder and Run calls explicitly. The Duet
conversation keeps its own `/model` setting; selecting a launch configuration
does not change the conversation. Foreground and background Duets each persist
their own launch selection.

Duet asks about project launch setup during initial design. It can propose a
configuration with `duet_launch_propose`; the human saves that proposal with
`/launch apply PROPOSAL_ID FILE`, or selects an existing file as below. Duet
receives current setup and approval state through `duet_status`, including the
available model slots. The conversational LLM can propose settings; approval
belongs to the human command surface.

`/launch apply PROPOSAL_ID FILE --replace` explicitly replaces an old-format or
invalid JSON file. Without that flag, an existing target must be a valid current
launch file. Replacement records the previous file's hash, not its contents;
there is no content backup or legacy-format conversion.

## Duet, refiner and target model boundary

The **Target Workflow** is the scoped Episode workflow being built, refined,
tested or executed. A **candidate revision** is one implementation state; a
**Run** is one execution. Neither term names the IterativeEpisodeRefiner.

The agreed routing boundary is:

| Work being performed | Model/provider configuration |
| --- | --- |
| Duet conversation | The Duet's own configuration |
| IterativeEpisodeRefiner and its reasoning children | The same configuration as the owning Duet |
| Test execution of the Target Workflow | The Target Workflow's explicitly selected launch configuration |

The refiner does **not** need a separate refiner launch file, and must not
inherit the Target Workflow's launch configuration merely because it requests
its execution. The shared harness resolves the Target Workflow's configuration
for that Run; it does not replace the caller's configuration. This remains
true when both happen to select the same model. Shared Duet/refiner model
settings do not mean shared prompts, transcripts, capabilities or authority.

Implementer's `change` calls use the existing Codex app-server coding runtime,
with that same pinned Duet model, effort and explicit credential. The initial
adapter supports the official `codex_responses` route; unsupported routes fail
explicitly rather than selecting an ambient Codex account or the target launch.
Its private native configuration disables extra agents and unrequested app/web
tools and limits command writes to the candidate workspace. Other refiner calls
retain the ordinary Duet transport. See [ADR 0009](../adr/0009-implementer-uses-an-existing-coding-agent.md).
The sandbox belongs to [Implementer's coding workspace](implementer_coding_workspace.md),
not the Target Workflow. Its setup must not become an implicit Target Workflow
environment requirement. Other coding backends use the same Implementer contract;
the current adapter is Codex-only.

Builder slots in a Target Workflow launch file configure the existing target
Builder calls. They do not select the refiner's reasoning model. A typed
`DuetLaunchRequest` supplies task inputs and is not a model/provider setting.
Execution and replay records must distinguish the configuration used by each
Run; credentials stay on the host and are never passed as child context.

For this development session, the target-test file is
`/home/chia/repos/OpenChia-iterative-refiner/launch_default.json`. It is **not**
the refiner's model configuration. Setup/resolution of that file proves neither
refiner execution nor target correctness.

Implementation status: `OpenChiaHost.refinement_experiment_service` binds the
campaign's owning Duet agent through `DuetEpisodeBinding.from_bound_agent`.
It freezes that agent's concrete route and the refiner build's declared model
slots for each physical attempt; credentials remain in host memory. Explicit
`/build continue` uses current owning-Duet model/effort settings for future calls.
Completed responses keep their original binding and are not regenerated merely
because the model changed. Refiner-job experiments use this
binding through the shared service, while target tests retain their approved
Target Workflow launch. Missing owning-Duet binding is an error, not a target fallback.
The lower-level `execute_refinement` entry still accepts a supplied broker;
that parameter alone is not evidence of Duet binding.

The host-bound service path has integration coverage with a supplied agent,
a local deterministic HTTP provider and an in-process executor. That verifies
route separation, not a fully initialized conversational agent, live reasoning
or native confinement. The normal build now uses the same binding when handing
its initial receipt to refinement; live end-to-end acceptance is still pending.
See [ADR 0007](../adr/0007-build-owns-iterative-finalization.md) and the
[verification receipts](unified_episode_test_harness_receipts.md) for exact coverage.

## Target Workflow launch commands

```text
/launch load /absolute/path/to/project/launch.json
/launch preview
/launch approve HASH_FROM_PREVIEW
/build
/launch calls
/run
```

`/launch` displays the selected project/mode and compact recorded-launch summaries.
`/launch show LAUNCH_ID` reads that launch's full persisted configuration and
provenance. `/launch preview` resolves the selected sources without a model
request or an auth refresh. `/launch calls` shows started, successful, failed
and cancelled attempts. Background
Duets use `/bg DUET_ID launch ...` with the same commands.

Approval binds the resolved, nonsecret configuration hash to this Duet's
selection. Builder and Run require that approval before model requests. Changes
to models, slots, endpoints, reasoning settings, or credential references require
another preview and approval. Architecture approval is a separate decision.

The same `/launch` → `/build` → `/run` path now supports an explicitly approved
testing Episode. Its Architecture must grant `episode_testing` and freeze the
targets, criteria, scopes and modes it may use. `/run` delegates to the shared
testing/refinement execution service; it does not grant testing access to other
Episodes. Separately, `/build` owns its automatic build → refine → validate job;
it does not wait for the user to launch refinement with `/run`. See the
[unified harness guide](unified_episode_test_harness_design.md#in-episode-access).

## Launch file

To create a launch file interactively without starting a Duet or contacting a
model, run:

```bash
openchia test setup-launch --directory /absolute/path/to/new/private-launch
```

The wizard asks for model routes, service endpoints, API modes, project-defined
function model slots, and the slots for Builder planning and emission. API keys are
entered without echo and saved separately in `credentials.env` in the new private
directory. Settings contain references, never key values. Existing directories
are not overwritten. Load the resulting file with
`/launch load /absolute/path/to/new/private-launch/launch.json`, then inspect
`/launch preview` and approve its exact hash with `/launch approve HASH`.
Setup does not grant approval. Harness `register-launch` requires the owning
Duet's existing approval of the exact current configuration.

For structured setup, `--from /path/to/existing/launch.json` preserves the
existing explicit environment/credential references. `--prompt-credentials`
optionally writes newly entered keys to the new private directory. Setup does
not change the current conversation's model or launch selection. A resolution
failure may leave a private credential file to inspect, but does not publish the
public launch file. External HTTP credentials retain their existing egress
configuration; this wizard configures model routing only.

This JSON file contains settings and credential references. `.env` files hold
the credentials. Relative `project_root` is relative to the launch file;
relative `env_files` paths are relative to that project root.

```json
{
  "project": "oscillator",
  "project_root": ".",
  "env_files": [".env"],
  "routes": {
    "design": {
      "provider": "openai",
      "model": "your-chosen-model",
      "base_url": "https://api.openai.com/v1",
      "api_mode": "chat_completions",
      "auth": {"kind": "env", "env": "PROJECT_API_KEY", "account": "project-billing-account"},
      "reasoning": {"enabled": true, "effort": "medium"},
      "fallbacks": []
    },
    "local": {
      "provider": "custom",
      "model": "your-local-model",
      "base_url": "http://127.0.0.1:8000/v1",
      "api_mode": "chat_completions",
      "auth": {"kind": "none"},
      "fallbacks": []
    }
  },
  "model_slots": {"reasoning": "design", "fast": "local"},
  "builder_slots": {"planning": "reasoning", "emission": "reasoning"}
}
```

Slot names are project-defined. Each LLM-using function declares its slot with
`CallOptions(model_type="reasoning")`, for example. Functions within one Episode
can use different slots. Changing the route assigned to a slot updates all its
consumers on subsequent approved launches. Changing which slot a function uses
is a materialized-code change. Builder receives the approved slot catalog,
records the selected `model_type` in each prompt specification, and rejects
unknown slots during planning. Run verifies those slots exist in its launch.

`CallOptions.model_type` is required, including for library calls. A reusable
function that contains model calls declares the argument names supplying their
slots in `provenance.model_slot_parameters` and requires those arguments in its
parameter schema. For example, the reasoning source takes
`selection_model_type` and `execution_model_type`. These are visible binding
arguments and can name different slots. Planning and Run preflight check both
prompt specifications and library binding dependencies against the launch.
The names `reasoning` and `fast` are examples, not mandatory project slots.

### Source precedence and model selection

Declared `.env` files supply credential references in list order, with the last file
winning. Missing or unreadable declared files fail resolution. Missing
referenced variables fail rather than invoking account/provider discovery.
The process environment supplies no credentials or launch settings. No `.env`
file is written into the process environment.

Resolution is eager: every declared route, including unused routes and
fallbacks, must have resolvable settings and credentials. A launch file declares
one complete configuration to freeze, rather than a menu with unavailable
accounts. Keep a project-specific set of routes in each file.

Provider, model, base URL, and API mode are literal nonsecret strings in the
launch JSON. Environment indirection in these fields is rejected before any
credential file is read, so credential-file values cannot be dereferenced into
public settings or Duet status. Each resolved field records its source.
Project root is an attribution and configuration-path base; it does not grant
workers filesystem access. Explicit credential-file paths may be outside it.

Builder calls use the slots in `builder_slots.planning` and
`builder_slots.emission`. Runtime calls use their own `model_type`. The slot
resolves to a route, which owns the concrete model, endpoint, credential
reference, reasoning setting, and explicit fallbacks. An unknown slot fails
before a model request. `ModelTier` describes the call shape's existing task
classification; it supplies no implicit slot. The host sets planning and emission
CallOptions from their respective approved slots, and records each stage's
effective options separately in the Builder identity.

An explicit route `reasoning` overrides the call's reasoning preference;
otherwise the existing call options apply. Temperature, output-token request,
timeout and effective reasoning preference are recorded per attempt. Existing
wire adapters translate these for the selected API (for example the Codex
adapter strips the local `-900k` model suffix and omits unsupported sampling
fields). The provider response's model identity is also recorded when exposed
by that adapter. An adapter's model field is not proof of a provider's immutable
backend revision.

An explicit timeout applies to SDK transport I/O, including receiving Responses
stream events. `timeout: None` keeps the original request unbounded and cancellable;
no auxiliary task-default timeout is inherited. Newly resolved routes also freeze
their [source health/recovery policy](model_call_recovery.md): inactivity can start
a bounded side call without cancelling the original. Only a successful probe,
continued silence and the frozen retry-capable policy permit replacement. Every
new source uses the same default algorithm, with optional saved user overrides;
there are no vendor-specific exceptions or request-status API requirements.
Historical frozen routes without a recovery field retain their legacy behavior.

### Credentials

`auth.kind: env` reads exactly the named variable from the selected sources.
`account` is an operator-supplied account label, not a verified billing identity;
OpenChia does not query account balances. The credential reference is recorded;
its value is held only by the host for that launch.

`auth.kind: none` sends no Authorization or API-key header. It is appropriate
for a local unauthenticated shim.

`auth.kind: codex_login` uses an explicitly selected Codex ChatGPT login:

```json
"auth": {"kind": "codex_login", "env": "WORKFLOW_CODEX_AUTH_FILE", "account": "my-codex-login"}
```

In the workflow's named `.env` file, set:

```dotenv
WORKFLOW_CODEX_AUTH_FILE=/absolute/path/to/.codex/auth.json
```

The reference must come from a declared workflow `.env`.
Each new launch reads that exact file once and snapshots its access token for
all routes sharing it. The route must use `openai-codex`, `codex_responses`, and
the official Codex endpoint. The file must contain `auth_mode: chatgpt` and a
non-expired access token. It never selects a Platform API key or another login.
The receipt records the `.env` variable and resolved login-file path; token
values stay in host memory. Resolution makes no network request and does not
verify quota or model entitlement.

Codex owns refresh of its login file. OpenChia reads the access token without
using or copying its rotating refresh token or changing the login file. A
running launch keeps its snapshot; a new launch picks up Codex's latest token.
If it expires, refresh that login in Codex and start a new launch. See
[Codex authentication](https://learn.chatgpt.com/docs/auth#login-caching).

Supported wires are `chat_completions`, `codex_responses`, and
`anthropic_messages`. The existing provider wire adapters perform serialization;
the ambient auxiliary routing/fallback machinery does not select the route.
Native Anthropic OAuth credentials use bearer authentication and the adapter's
OAuth request/response handling; API keys use the API-key header. Inactive
authentication and OpenAI organization/project headers are explicitly omitted.
HTTP clients use direct networking with normal TLS verification and no ambient
proxy inheritance or redirects. Transport settings such as proxies
and provider-specific arbitrary headers are not supported in this launch format.

### Stable launches, new launches and repeating settings

Each preview, approval, `/build`, and `/run` rereads the selected launch file
and its explicit environment references. A launch freezes the approved result
for its entire lifetime, including fallbacks. Editing files, the selection, or
the Duet model does not change an in-flight launch. Credential rotation at the
same reference is picked up by the next launch without changing its approval;
secret values are neither persisted nor included in the approval hash.

`/launch reload` rereads the source file for subsequent launches. Those launches
resolve environment references anew. `/launch reuse LAUNCH_ID` instead selects
that launch's resolved nonsecret settings instead of following file edits.
Credential references are still read anew: secret
values are never persisted, and rotation is possible. Reuse therefore repeats
routing settings, not exact credentials, provider internals or model output.
While reuse mode is selected, `/launch reload` asks you to select a file with
`/launch load FILE`; it keeps the frozen selection intact.

API failures stop the owning build/refinement/Run and require explicit
continuation. `fallbacks` remains readable in historical launch configurations,
but a failed API request does not advance to those routes. SDK retries and
implicit provider/account hopping are disabled. A still-pending silent call can
use bounded physical replacement under its frozen health policy; this is not
retry-on-error. See [continuation](build_continuation.md#api-errors-stop-the-owning-job).

## Durable receipts and boundaries

The existing Duet event store records `launch_configuration_proposed`,
`launch_proposal_applied`, `launch_configuration_selected`, `launch_configuration_approved`,
`model_launch_resolved`, and `model_launch_call`. Each resolved launch binds a
build-request ID or Run ID to a content-addressed configuration blob in the
Builder's blob store. Its receipt includes source paths, requested and resolved
settings, credential references, host/adapter source
hashes, checkout commit/dirty state, and SDK package versions. These records
survive reopening the same Duet.

Every physical model attempt records launch ID, configuration hash, call ID,
Episode local ID, call role, model slot, provider, model, endpoint, credential source,
operator account label, outcome and elapsed time. Failed attempts retain exception
type, HTTP status and OpenChia's classification separately from the provider's
error code/type, parameter, redacted bounded message, request ID and retry-after
header when present. `/launch calls` exposes these in the existing call records;
physical-attempt records also preserve a response-header request ID when the
SDK's streaming exception omits it. Missing, redacted and truncated information
is explicit. Raw response bodies and credentials are not stored. See
[failure reporting](model_call_recovery.md#audit-and-implementation) for the
redaction and size limits.
An interrupted process can leave a `started` receipt without a terminal
receipt; it must not be interpreted as success.

The worker supplies its structural Episode path; the protocol checks its
runtime identity and the host broker matches it to the admitted tree before
dispatching its function's model slot. Endpoint and credential configuration stay
on the host. Changing this worker protocol requires a fresh runtime package;
there is no old-frame compatibility path.

This feature concerns target Builder and Run model calls. It does not reroute
the Duet or its IterativeEpisodeRefiner. External acquisition services
use the existing host egress configuration; `duet_status` reports its allowed
hosts and credential names so Duet can ask for missing setup during design.
Those credentials are not model routes. Refiner design/credit logic retains
its existing ownership.

The native Messages wire requires the repository's optional `anthropic` extra.
A missing SDK is recorded as a failed attempt; it never switches to another
wire or account implicitly.

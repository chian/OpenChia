# Episode launch configuration

Select the project and model routes for Builder and Run explicitly. The Duet
conversation keeps its own `/model` setting; selecting a launch configuration
does not change the conversation. Foreground and background Duets each persist
their own launch selection.

```text
/launch load /absolute/path/to/project/launch.json
/launch preview
/build
/launch calls
/run
```

`/launch` displays the selected specification and recorded launches. `/launch
preview` resolves sources without a model request or an auth refresh. `/launch
calls` shows started, successful, failed and cancelled attempts. Background
Duets use `/bg DUET_ID launch ...` with the same commands.

## Launch file

This JSON file contains settings and credential references. `.env` files hold
the credentials. Relative `project_root` is relative to the launch file;
relative `env_files` paths are relative to that project root.

```json
{
  "project": "oscillator",
  "project_root": ".",
  "env_files": [".env"],
  "inherit_env": ["EPISODE_MODEL"],
  "routes": {
    "design": {
      "provider": "openai",
      "model": {"env": "EPISODE_MODEL"},
      "base_url": "https://api.openai.com/v1",
      "api_mode": "chat_completions",
      "auth": {"kind": "env", "env": "PROJECT_API_KEY", "account": "project-billing-account"},
      "reasoning": {"enabled": true, "effort": "xhigh"},
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
  "bindings": {
    "default": "design",
    "roles": {"builder.planning": "design", "builder.emission": "design"},
    "episodes": {"simulation": "local"}
  }
}
```

Use actual local Episode IDs from the Architecture in `bindings.episodes`.
Unknown IDs are rejected before model requests. The example's `simulation`
entry should be removed or replaced for a different workflow.

### Source precedence and model selection

Only variables named in `inherit_env` are read from the process environment.
Declared `.env` files overlay those values in list order, with the last file
winning. Missing or unreadable declared files fail resolution. Missing
referenced variables fail rather than invoking account/provider discovery.
No `.env` file is written into the process environment.

Provider, model, base URL, and API mode can be literal strings or explicit
`{"env": "VARIABLE_NAME"}` references. Other fields live in the launch file.
Each resolved field records its source. Project root is an attribution and
configuration-path base; it does not grant workers filesystem access.

Builder calls select `builder.planning` or `builder.emission`, then the call's
task binding, then `default`. Runtime calls select the Episode override, then
`run`, then their task binding, then `default`. Task binding names are
`episode_structured_json_reasoning`, `episode_structured_json_fast`,
`episode_probability_reasoning`, and `episode_probability_fast`. Episode
overrides affect running Episodes, not the model writing their code.

An explicit route `reasoning` overrides the call's reasoning preference;
otherwise the existing call options apply. Temperature, output-token request,
timeout and effective reasoning preference are recorded per attempt. Existing
wire adapters translate these for the selected API (for example the Codex
adapter strips the local `-900k` model suffix and omits unsupported sampling
fields). The provider response's model identity is also recorded when exposed
by that adapter. An adapter's model field is not proof of a provider's immutable
backend revision.

### Credentials

`auth.kind: env` reads exactly the named variable from the selected sources.
`account` is an operator-supplied account label, not a verified billing identity;
OpenChia does not query account balances. The credential reference is recorded;
its value is held only by the host for that launch.

`auth.kind: none` sends no Authorization or API-key header. It is appropriate
for a local unauthenticated shim.

`auth.kind: session` explicitly borrows the current Duet session's concrete
credential. Supply an `account` label and literal/resolved provider, endpoint
and API mode matching that session. A mismatch fails before dispatch. This
option snapshots the credential; it does not discover another login, rotate a
credential pool, or refresh OAuth tokens. An expired token requires a refreshed
session credential and a new launch. Use a dedicated `.env` reference when
account isolation must be independent of the conversational session.

Supported wires are `chat_completions`, `codex_responses`, and
`anthropic_messages`. The existing provider wire adapters perform serialization;
the ambient auxiliary routing/fallback machinery does not select the route.
HTTP clients use direct networking with normal TLS verification and no ambient
proxy inheritance or cross-host redirects. Transport settings such as proxies
and provider-specific arbitrary headers are not supported in this launch format.

### Stable launches, new launches and repeating settings

The selected launch file is captured when loaded. Each `/build` or `/run`
resolves its explicit environment references once and freezes that result for
the entire launch, including fallbacks. Editing `.env`, the process environment,
the selection, or the Duet model does not change an in-flight launch.

`/launch reload` rereads the source file for subsequent launches. Those launches
resolve environment references anew. `/launch reuse LAUNCH_ID` instead selects
that launch's resolved nonsecret settings, so model/endpoint variables no longer
follow the environment. Credential references are still read anew: secret
values are never persisted, and rotation is possible. Reuse therefore repeats
routing settings, not exact credentials, provider internals or model output.

`fallbacks` is an ordered list of route names. After an attempt fails, only the
listed routes are attempted, once each. Fallback lists on those entries are not
recursively expanded. Cancellation stops the call rather than advancing to a
fallback. SDK retries and implicit provider/account hopping are disabled.

## Durable receipts and boundaries

The existing Duet event store records `launch_configuration_selected`,
`model_launch_resolved`, and `model_launch_call`. Each resolved launch binds a
build-request ID or Run ID to a content-addressed configuration blob in the
Builder's blob store. Its receipt includes source paths, requested and resolved
settings, inheritance policy, credential references, host/adapter source
hashes, checkout commit/dirty state, and SDK package versions. These records
survive reopening the same Duet.

Every physical model attempt records launch ID, configuration hash, call ID,
Episode local ID, call role, provider, model, endpoint, credential source,
operator account label, outcome and elapsed time. Failed attempts retain error
type and HTTP status without storing raw provider errors that may contain
secrets. An interrupted process can leave a `started` receipt without a terminal
receipt; it must not be interpreted as success.

The worker supplies its structural Episode path; the protocol checks its
runtime identity and the host broker matches it to the admitted tree before
selecting the local Episode's route. Endpoint and credential configuration stay
on the host. Changing this worker protocol requires a fresh runtime package;
there is no old-frame compatibility path.

This feature concerns Builder and Run model calls. Duet conversation routing,
external acquisition-tool credentials, and Refiner design/credit logic retain
their own existing ownership.

The native Messages wire requires the repository's optional `anthropic` extra.
A missing SDK is recorded as a failed attempt; it never switches to another
wire or account implicitly.

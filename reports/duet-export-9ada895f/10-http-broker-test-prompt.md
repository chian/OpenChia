# Test prompt: one brokered HTTP call end-to-end (paste with `/paste`)

Purpose: prove the whole chain — Duet declares `egress_allowlist` → approval → EpisodeBuilder
materializes → container Run → worker issues `http_request` → host broker checks the rule, injects the
`patric` credential, records `HTTP_REQUESTED`/`HTTP_RESPONDED` → typed result. Keep it as small as the
protocol allows; the RAGstack study comes after this works.

```
Design the smallest possible workflow that proves a Run can reach the BV-BRC RAGstack asm-next API
through the host HTTP broker. One root Episode, no children.

Goal: confirm the asm-next tenant is reachable and the credential is accepted, by performing two
read-only GET requests and reporting their status codes and response sizes as the typed result.

Unit: one GET request. Exactly two units:
  1. GET https://www.bv-brc.org/ragstack/asm-next/api/health         (no credential needed)
  2. GET https://www.bv-brc.org/ragstack/asm-next/api/v1/collections (needs the "patric" credential)
Use the http_json library function (or http_request) from http_call_library; do not write any HTTP
client code and do not try to read any token — the host attaches it.

Result (typed status): for each unit the method, path, outcome, HTTP status, response byte count, and
for /v1/collections the number of collections returned (or the failure kind). Overall success means
both calls returned outcome "ok" with status 200.

egress_allowlist for this Episode (exactly these two rules, read_only true):
  - name: asm_health       host: www.bv-brc.org  path_prefix: /ragstack/asm-next/api/health   
    methods: [GET]  max_requests: 2  max_response_bytes: 65536   credential: null
  - name: asm_collections  host: www.bv-brc.org  path_prefix: /ragstack/asm-next/api/v1/collections
    methods: [GET]  max_requests: 2  max_response_bytes: 262144  credential: patric

Stopping: after the two units. No model judgement is needed anywhere in this Episode. Keep every
other field minimal and propose the Architecture now; ask only if something above is impossible.
```

After `/review` and `/approve`, build and run it. Evidence lands under
`~/.hermes/openchia/episode_runs/events/<run_id>/` — expect `http_requested` then `http_responded`
events naming the rule, the request/response hashes, outcome and status, and never the token.

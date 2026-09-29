# Generic Creator v1 migration

The v1 migration is executed idempotently by `GenericCreatorStore`. It adds
only tables whose names begin with `generic_` and records version `1` in
`generic_schema_migrations`. It does not alter existing Duet drafts,
artifacts, approvals, Creators, evidence, launches, or Episode contracts.

Apply it only with OpenChia stopped:

1. Back up the Duet SQLite database and its WAL/SHM companions.
2. Check out the reviewed commit in a controlled environment.
3. Run the affected test suite documented in the change report.
4. Open and close `GenericCreatorStore` on a copy of the database; verify the
   migration marker and existing-row counts.
5. Configure the feature flag (`recursive_creators_enabled`), capability/depth
   policy, workspace roots, protected roots, and—only if effectful recursive
   Episodes are required—a real isolated executor.
6. Start a new frozen host. Do not hot-reload a process admitted under the old
   runtime identity.

Rollback requires stopping the host and restoring the prior code/database
backup. The additive tables may also be left unused; old code does not read
them. There is no Creator-contract migration because existing schema-v4
contracts and approval invalidation semantics are unchanged.

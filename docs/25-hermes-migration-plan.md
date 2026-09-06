# Historical migration reference

This repository is frozen as the OpenClaw predecessor of
[My AI Office](https://github.com/eiler2005/my-ai-office).

The former migration plan, implementation, and active acceptance work now live
in the [migration/hermes-native](https://github.com/eiler2005/my-ai-office/tree/migration/hermes-native)
branch of that repository. It contains the Hermes deployment, the Benka
integration package, bridge implementations, migration tooling, and tests.

The final OpenClaw result was deliberately not a production cutover: the
2026.9.1 candidate failed its Gateway readiness gate, and the restored
2026.6.9 Gateway remains the legacy recovery reference. See
[the freeze record](26-archive-and-migration.md) for the outcome and the
functional handoff.

# Agent instructions

## Scope

This repository owns the Home Assistant side of the Samvev integration.

The Samvev backend, API authorization, display pairing, projection logic and iframe support belong in https://github.com/pabben/samvev. PR #25 remains there.

Do not copy the Samvev application or introduce another running service without a concrete requirement.

## Implementation

- Inspect current Samvev code and official Home Assistant documentation before selecting implementation details.
- Verify API endpoints, payloads and authentication; do not invent working contracts.
- Keep the initial implementation small: configuration, connection handling and one read-only capability selected from available APIs and documented requirements.
- Put household permissions and business rules in Samvev. Respect those boundaries in HA.
- Link required upstream changes to issues or PRs in the Samvev repository.
- Keep versions and compatibility requirements explicit.
- Follow Home Assistant conventions for asynchronous I/O, configuration, entity identity, unloading and error handling.

## Data and credentials

- Use synthetic fixtures and test accounts.
- Never commit credentials or real household data.
- Exclude secrets and personal payloads from logs and diagnostics.
- Do not weaken authentication to make a demonstration work.

## Validation and reporting

- Test behavior meaningful to the change, including authentication failures and unavailable services.
- Report what is implemented, what was tested and what remains unverified.
- Distinguish planned features from delivered functionality.
- Do not claim HACS availability, hardware validation or production deployment without evidence.
- Documentation-only setup does not authorize changes to an existing HA or Samvev runtime.

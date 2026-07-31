# Security Policy

## Supported versions

Multi-Agent Governor is experimental. Security fixes are provided for the
latest `0.2.x` release line and the current `main` branch.

| Version | Supported |
| --- | --- |
| `0.2.x` | Yes |
| `< 0.2` | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use the repository's **Security → Report a vulnerability** flow to send a
private report to the maintainers. Include:

- the affected version or commit;
- the threat scenario and security boundary crossed;
- minimal reproduction steps;
- expected and observed behavior;
- any suggested mitigation;
- whether the issue is already public.

Avoid attaching credentials, production data, proprietary repositories, or
unredacted Agent traces. Use a minimal synthetic reproduction when possible.

The maintainers will acknowledge a complete report within seven days, keep the
reporter informed of material progress, and coordinate disclosure after a fix
or mitigation is available. Timelines may vary because the project is
maintainer-led and experimental.

## Security scope

High-priority reports include:

- bypassing configured Agent, token, time, tool, or sandbox limits;
- leaking truth cards, hidden tests, prior Agent traces, credentials, or user
  configuration into an isolated Agent workspace;
- executing unrestricted Codex flags despite runtime guardrails;
- event-log or report tampering that changes an auditable admission decision;
- command injection through runtime configuration.

Model quality disagreements and ordinary false positives are evaluation issues,
not security vulnerabilities, unless they cross one of these boundaries.

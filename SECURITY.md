# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 1.x | Yes |
| < 1.0 | No |

Security fixes are released as patch versions of the latest minor release.

## Reporting a vulnerability

Please **do not** open a public issue. Report it privately through
[GitHub security advisories](https://github.com/lobojoel2003/Langdesk/security/advisories/new).
Include the version (page footer or `/healthz`), steps to reproduce and the impact you expect.

You'll get an acknowledgement within three working days and a plan within ten. We'll credit you
in the release notes unless you'd rather we didn't.

## How Langdesk protects data

- Requests hold an appointment reference, never client names, birth dates or diagnoses, and
  free-text fields reject common identifiers.
- Offer links and calendar feeds use long random tokens; offer pages only change state on
  `POST`, so email link scanners can't accept jobs. Feed links can be reissued at any time.
- Inbound Twilio webhooks are verified with `X-Twilio-Signature`; the generic webhook requires a
  bearer token and is disabled until one is configured.
- The container runs as a non-root user. Production settings (`check --deploy`) are verified in
  CI, and dependencies are watched by Dependabot and CodeQL.

## Your responsibilities when self-hosting

Serve Langdesk over HTTPS, keep `DJANGO_SECRET_KEY` and provider tokens secret, restrict who can
reach the admin, back up the database, and apply patch releases promptly.

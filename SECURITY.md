# Security policy

This repository is a reference implementation, not an operating service. It
does not accept credentials, call a model provider, execute generated commands,
or create remote pull requests.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature. Do not include
secrets, private source code, or exploit data in a public issue.

Include the affected version, a minimal reproduction using synthetic data, the
expected safety property, and the observed behavior. Reports that demonstrate
path escape, approval bypass, symlink traversal, plan tampering, or unapproved
command execution are especially useful.

## Supported versions

Security fixes are applied to the latest version on the default branch. This
project is currently pre-1.0 and does not promise backward compatibility.

See [docs/security-model.md](docs/security-model.md) for trust boundaries,
controls, limitations, and production-hardening guidance.

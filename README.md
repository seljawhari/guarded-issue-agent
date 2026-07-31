# Guarded Issue Agent

[![CI](https://github.com/seljawhari/guarded-issue-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/seljawhari/guarded-issue-agent/actions/workflows/ci.yml)

Guarded Issue Agent is a small reference implementation for a deliberately
limited workflow:

1. read a structured issue and a repository,
2. collect file-and-line evidence,
3. write a deterministic change plan,
4. stop for human approval of that exact plan, and
5. apply scoped text replacements and produce a local patch plus draft PR.

It does **not** run generated commands, invoke a shell, call a model provider,
use credentials, create branches, push code, or contact GitHub. The included
"model" is an offline deterministic adapter for a synthetic fixture. The point
is to make the controller and its safety boundaries easy to inspect and test.

## Why this exists

Issue-to-PR demos often spend most of their time on the model call. This project
focuses on the part that still matters when model output is wrong or hostile:
what the trusted controller will permit.

The implementation treats issue text, repository contents, and model output as
untrusted. A plan needs evidence, paths stay inside configured roots, symlinks
are rejected, files have size limits, exact matches must be unique, and the
workspace must match the hashes collected during planning when it is checked.
Applying a plan requires the operator to paste its SHA-256 digest. These checks
detect ordinary stale plans; they are not filesystem locks against a concurrent
local writer.

## Quick start

Python 3.11 or newer is required. Runtime code uses only the standard library.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

DEMO_DIR="$(mktemp -d)/guarded-demo"
guarded-issue-agent init-demo --output "$DEMO_DIR"

guarded-issue-agent plan \
  --workspace "$DEMO_DIR/repo" \
  --issue "$DEMO_DIR/issue.json" \
  --out "$DEMO_DIR/run"
```

At this point no repository file has changed. Open `run/plan.json`, inspect the
evidence and replacements, and copy the `plan_sha256` value. Approval is a
separate command on purpose:

```bash
guarded-issue-agent apply \
  --workspace "$DEMO_DIR/repo" \
  --plan "$DEMO_DIR/run/plan.json" \
  --approve PASTE_THE_REVIEWED_PLAN_SHA256_HERE
```

The apply command changes the approved file in the disposable demo workspace
and writes three artifacts beside the plan:

- `approval.json` records the approval mechanism and digest;
- `changes.patch` is a standard unified diff;
- `draft-pr.md` links the change back to evidence and acceptance criteria.

The tool recommends tests but never executes them. Run the synthetic test
yourself:

```bash
cd "$DEMO_DIR/repo"
python -m unittest discover -s tests -v
```

## Safety invariants

| Boundary | Enforced behavior |
| --- | --- |
| Workspace | Canonical root, regular UTF-8 files only, no symlink components |
| Paths | Relative paths under `src`, `tests`, or `docs` by default |
| Changes | Existing files only, allowlisted extensions, bounded sizes |
| Evidence | Exact match, file and line citation, file SHA-256 precondition |
| Approval | Operator must supply the digest of the exact serialized plan |
| Apply | All changes preflight before writes; detected stale or ambiguous plans stop |
| Execution | No shell, test, git, network, credential, or remote PR operations |
| Artifacts | Run directory must be outside the workspace; existing files are not overwritten |

These controls reduce risk; they do not make this a hardened multi-tenant
sandbox. Read [the security model](docs/security-model.md) before adapting it to
real repositories.

## Commands

### `init-demo`

Creates a new synthetic repository and issue. It refuses to overwrite an
existing path.

### `plan`

Uses the deterministic mock adapter to collect evidence and write `plan.json`.
Use `--allow-root NAME` repeatedly to replace the default editable roots.

### `apply`

Validates the saved plan, its digest, the approval value, current file hashes,
path policy, and unique replacements before writing anything. It emits local
review artifacts and performs no remote action.

## Adding a real model adapter

`ModelAdapter` is intentionally narrow: it receives a validated issue and a
restricted `Workspace`, then returns a `Plan`. A production adapter should run
outside the write-capable controller and return the same typed data. Do not give
the model a shell, repository credentials, or a network-capable tool set.

A real integration also needs controls that are outside this example:

- an OS-level sandbox or isolated worker;
- egress restrictions and short-lived credentials;
- secret and personal-data redaction before model calls;
- provider-specific retention and data-residency review;
- authenticated operator identity and tamper-evident audit storage;
- a separate, least-privilege service that creates the remote draft PR only
  after approval and validation.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

The CI workflow runs both commands on Python 3.11 through 3.14 with read-only
repository permissions and commit-pinned GitHub Actions.

## Repository map

- `src/guarded_issue_agent/` - controller, policy, sandbox, plan schema, CLI
- `tests/` - approval, integrity, path, symlink, stale-plan, and CLI tests
- `docs/architecture.md` - component and sequence design
- `docs/security-model.md` - threats, controls, limitations, hardening steps
- `PROVENANCE.md` - origin and public-safety statement

## License

MIT. See [LICENSE](LICENSE).

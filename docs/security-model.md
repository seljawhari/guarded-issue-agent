# Security model

## Assets

- source code and its integrity;
- secrets or personal data that may exist in a repository or issue;
- operator intent and approval history;
- source-control credentials and remote repository state.

## Trust boundaries

The issue body, repository contents, and model output are untrusted. A malicious
file can contain prompt injection. A malicious issue can request a sensitive
path. A compromised model can invent evidence, broaden scope, or propose a
destructive change.

The local operator and controller process are trusted in this reference. The
controller has no source-control credentials and no network or command tool.

## Threats and controls

### Path escape and sensitive-file modification

Controls: relative POSIX paths, configured top-level roots, extension allowlist,
hidden-path rejection, canonical workspace boundary, per-component `lstat`, and
symlink rejection. Plans cannot target `.git`, `.env`, workflow credentials, or
files outside the configured roots under the default policy.

### Prompt injection and over-broad model output

Controls: the model never receives a shell or write primitive. Its plan is
parsed into a strict schema and checked by controller-owned policy. Each change
must cite evidence for the same path and file digest.

### Approval substitution or plan tampering

Controls: canonical JSON is hashed with SHA-256. The saved envelope is verified
when loaded, and the operator must supply the exact digest. A changed plan needs
new review and approval.

### Time-of-check/time-of-use changes

Controls: planning records a full-file digest. Apply re-reads every file before
any write, requires exactly one approved match, and checks the digest again
immediately before atomic replacement.

### Command or dependency execution

Controls: runtime code uses the Python standard library, does not install at
runtime, and exposes no command executor. Test recommendations are rendered as
text. No issue or plan field is passed to a shell.

### Remote side effects and credential misuse

Controls: there is no git client, provider SDK, HTTP client, credential loader,
branch creation, push, or PR API integration in the workflow.

### Artifact overwrite

Controls: the plan uses a new or empty run directory outside the workspace.
Apply artifacts use exclusive creation and are never silently overwritten.

## Known limitations

- This is an application-level guard, not an OS sandbox. A vulnerability in the
  Python process or interpreter is out of scope.
- A local user who can race and mutate files or directories may exceed the
  assumptions of the path and hash checks. Hash verification is not an atomic
  compare-and-swap with `os.replace`; a writer can change a file in the final
  check-to-replacement window. Do not use this design as a multi-tenant or
  concurrent-writer boundary.
- Atomic replacement is per file. Best-effort rollback is not a filesystem
  transaction across several files.
- Evidence snippets and issue text may themselves be sensitive. Store run
  artifacts outside the repository and apply normal retention controls.
- SHA-256 approval proves which plan was accepted, not who approved it. This
  demo does not authenticate operator identity.
- The deterministic mock fixture trusts its explicit change hints only to make
  controller behavior reproducible. A real adapter must be isolated and its
  output treated as hostile.

## Production hardening checklist

Before using this pattern on private or important source code:

1. Run analysis in an ephemeral container or VM with a read-only checkout.
2. Disable network egress by default and broker any provider call separately.
3. Redact secrets and personal data before content crosses a provider boundary.
4. Store plan, approval identity, policy version, patch, and result in a
   tamper-evident audit system.
5. Require authenticated review in a user interface that shows the full diff,
   evidence, tests, and policy exceptions.
6. Run tests in a separate sandbox with CPU, memory, time, process, and network
   limits. Never execute a model-provided command directly.
7. Give a remote PR service short-lived credentials restricted to one
   repository and draft-PR creation. It should accept only a validated patch.
8. Add repository-specific path policy and code-owner approval.
9. Threat-model dependencies, build scripts, hooks, submodules, large files,
   Unicode confusables, and platform-specific filesystem behavior.

## Safe evaluation

Use only synthetic repositories and issues while evaluating this code. The
included demo contains no external names, proprietary logic, credentials,
customer data, or production configuration.

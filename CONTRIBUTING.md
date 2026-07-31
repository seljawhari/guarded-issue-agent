# Contributing

Keep changes small, testable, and explainable. New behavior should fail closed
when an input is ambiguous.

1. Create a focused branch.
2. Add or update tests for the safety property being changed.
3. Run `python -m unittest discover -s tests -v`.
4. Document any new trust boundary or limitation.
5. Open a pull request that explains the threat being addressed and the
   expected operator experience.

Never contribute private source code, issue text, credentials, customer data,
or configuration copied from an employer or client.

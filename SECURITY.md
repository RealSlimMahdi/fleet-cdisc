# Security Policy

## Reporting a vulnerability

Do not open a public issue for a security problem.

Report it privately through GitHub:
[Report a vulnerability](https://github.com/RealSlimMahdi/fleet-cdisc/security/advisories/new)
(repository tab "Security", then "Report a vulnerability").

Give the Fleet version (`fleet --version`), the steps to reproduce, and the
effect. The maintainer replies in the advisory.

## Supported versions

Fleet is in alpha. Only the latest release gets security fixes.

## Trust model

A study folder is code, not data:

- `callable:` and `derivations_module:` in a `define.yaml` import and run
  Python.
- `validation.engine_path` in a `study_config.yaml` starts a program.
- An `expression:` string is checked against an allow-list of Polars names and
  methods. The allow-list stops mistakes. It is not a security boundary.

Read a `define.yaml` or a `study_config.yaml` from another party before you
run it.

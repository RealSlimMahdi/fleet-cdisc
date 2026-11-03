# Test Status

Fleet uses [pytest](https://docs.pytest.org/) with coverage reporting.

## Run the test suite locally

```bash
# Install dev dependencies
uv sync --extra dev

# Run all tests
uv run pytest

# With coverage report
uv run pytest --cov=fleet --cov-report=term-missing
```

## CI status

GitHub Actions runs these checks:

- **Every pull request and every push to main** (`ci.yml`): ruff, the docs
  formatter, the generated-reference checks and the tests on Python 3.12, 3.13
  and 3.14 (each leg checks that it runs the Python in its name). The 3.12 leg
  installs every extra, so the LSP, MCP, migrate and render tests run, and it
  runs the eight example scripts.
- **Weekly and before each release** (`fresh-install.yml`): the built wheel is
  installed with no lock file, as a user gets it, and the tests and examples run
  against the installed package.
- **Weekly** (`admiral-oracle.yml`): a grid of real ADAE shapes runs through
  admiral 1.4.1 and through Fleet, and every cell is compared.
- **Weekly** (`core-canary.yml`): validation runs on the newest CDISC CORE release.

[![CI](https://github.com/RealSlimMahdi/fleet-cdisc/actions/workflows/ci.yml/badge.svg)](https://github.com/RealSlimMahdi/fleet-cdisc/actions/workflows/ci.yml)

## Test structure

```
tests/
├── conftest.py          # Shared fixtures (raw DataFrames, SDTM domains)
├── fixtures/
│   ├── ct/              # Sample controlled terminology YAML
│   ├── raw/             # ae_raw.csv, dm_raw.csv, vs_raw.csv
│   └── specs/           # define_adam.yaml, define_sdtm.yaml
└── unit/
    ├── test_adam_namespace.py
    ├── test_adsl_namespace.py
    ├── test_ct_validation.py
    ├── test_define_xml.py
    ├── test_metabolic_namespace.py
    ├── test_neuro_namespace.py
    ├── test_occds_namespace.py
    ├── test_onco_namespace.py
    ├── test_ophtha_namespace.py
    ├── test_peds_namespace.py
    ├── test_sdtm_namespace.py
    └── test_vaccine_namespace.py
```

## Coverage targets

| Module       | Target |
| ------------ | ------ |
| `sdtm`       | ≥ 90%  |
| `adam`       | ≥ 90%  |
| `adsl`       | ≥ 90%  |
| `define_xml` | ≥ 85%  |
| `ct`         | ≥ 85%  |

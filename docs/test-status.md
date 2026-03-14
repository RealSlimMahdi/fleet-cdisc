# Test Status

Pymaverse uses [pytest](https://docs.pytest.org/) with coverage reporting.

## Run the test suite locally

```bash
# Install dev dependencies
uv sync --extra dev

# Run all tests
uv run pytest

# With coverage report
uv run pytest --cov=pymaverse --cov-report=term-missing
```

## CI status

Tests run automatically on every push and pull request via GitHub Actions.

[![CI](https://github.com/pymaverse/pymaverse/actions/workflows/ci.yml/badge.svg)](https://github.com/pymaverse/pymaverse/actions/workflows/ci.yml)

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

| Module | Target |
|--------|--------|
| `sdtm` | ≥ 90% |
| `adam` | ≥ 90% |
| `adsl` | ≥ 90% |
| `define_xml` | ≥ 85% |
| `ct` | ≥ 85% |

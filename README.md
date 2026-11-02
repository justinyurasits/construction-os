# Construction OS

The application. It generates governed construction documents from a customer package, and reads only that package. Beacon Hill Interiors' package is in `construction-os-corpus`.

The build spec is `../construction-os-corpus/design/pco-technical-design.md`.

## Setup

```
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
```

## Validate a package

```
.venv/bin/python -m construction_os.validate --corpus ../construction-os-corpus
```

It reports pass or fail for four checks and exits non-zero on any failure:

- `registry_entries`: every registry file matches the entry schema.
- `config_values`: `company/config.yaml` values match their registry types and constraints.
- `definition_dependencies`: every `CHG-53-DEF` dependency resolves to a POL-01 rule, a document in `docs/`, or a registry parameter.
- `sample_draft`: `samples/pco_sample_draft.json` validates against `schemas/pco_draft.schema.json`.

## Test

```
.venv/bin/pytest
```

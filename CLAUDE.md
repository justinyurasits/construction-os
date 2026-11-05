# Construction OS

## What this is

The application. It generates governed construction documents from a customer package. The first customer package is construction-os-corpus, next to this repository.

## Build spec

../construction-os-corpus/design/pco-technical-design.md is the build spec. Read it, and ../construction-os-corpus/design/product-brief.md, before proposing a plan or next step. They are snapshots; check the date at the top.

## Checks

Every PR runs the tests and `python -m construction_os.validate --corpus ../construction-os-corpus`. A failure is never ignored. Either the change is wrong or the check is.

## Rules

- Never commit or push directly to main. Every change goes on a branch and through a pull request.
- Never read, print, or edit .env. Secrets live only there. .env.example holds placeholder key names only.
- Show me the plan before writing code.
- Never put company content in this repository: no company names, rates, rules, clause text or templates. Everything company-specific is read from the package. Test fixtures use clearly fictional companies.
- Don't merge a pull request unless told.

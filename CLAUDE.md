# Document workbench

## What this is

The Construction OS document workbench: the application that generates governed construction documents from a customer package. The first customer package is construction-os-corpus, next to this repository. The design docs are in the construction-os-design repository, also next to this one.

## Build spec

Before proposing a plan or next step, read from ../construction-os-design/construction-os/:

- document-workbench/pco-design.md: the build spec for the PCO slice
- brief.md: the governing product reference
- document-workbench/design.md: the architecture and the decision log
- document-workbench/plan.md: the work and what's next
- principles.md: the rules every design decision follows

Pull construction-os-design first. Its files are synced from Claude Docs; the header at the top of each gives the revision and sync date, and the Claude Doc linked there is current if the two differ. If something in this repo or the corpus contradicts them, say so; don't guess.

## Checks

Every PR runs the tests and `python -m construction_os.validate --corpus ../construction-os-corpus`. A failure is never ignored. Either the change is wrong or the check is.

## Rules

- Never commit or push directly to main. Every change goes on a branch and through a pull request.
- Never read, print, or edit .env. Secrets live only there. .env.example holds placeholder key names only.
- Show me the plan before writing code.
- Never put company content in this repository: no company names, rates, rules, clause text or templates. Everything company-specific is read from the package. Test fixtures use clearly fictional companies.
- Don't merge a pull request unless told.

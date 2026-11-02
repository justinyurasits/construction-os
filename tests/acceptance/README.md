# PCO acceptance cases

Five situations for the PCO slice (design section 9). The slice is graded on the documents it produces.

## Layout

Each folder in `cases/` has two files:

- `request.md`: the PM's words. This is the only input.
- `expected.yaml`: the expected results. It's never given to the system.
  - `exact`: must match: totals, rule IDs, the document chosen.
  - `judged`: reviewed by a person.
  - `review_notes`: open questions about the case. Not graded.

## How to run them

Run each request in a fresh conversation against the same company package. Save the full response: citations, assumptions, proposed pricing and any Word files.

Grade on knowledge and rules, document selection, pricing and facts, and how useful the draft is.

Start with case 1 to prove the pipeline, then case 4 for deterministic pricing, then cases 2, 3 and 5.

## What the tests do today

The application can't produce a response yet, so `test_cases.py` checks the cases themselves: the request stays separate from the answers, the arithmetic is right, and every citation resolves in the package. The grading tests are skipped until the drafting pipeline exists (build step 5).

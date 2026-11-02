"""Checks the acceptance cases themselves; grading waits for the pipeline."""
import os
import re
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

CASES = sorted(p for p in (Path(__file__).parent / "cases").iterdir() if p.is_dir())
CORPUS = Path(os.environ.get("CORPUS", Path(__file__).resolve().parents[3] / "construction-os-corpus"))


def expected(case):
    return yaml.safe_load((case / "expected.yaml").read_text())


def request(case):
    return (case / "request.md").read_text()


def cents(value):
    return Decimal(value).quantize(Decimal("0.01"))


def priced_cases():
    return [c for c in CASES if "pricing" in expected(c)["exact"]]


def test_there_are_five_cases():
    assert [expected(c)["id"] for c in CASES] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_case_has_exact_and_judged_results(case):
    data = expected(case)
    assert data["mode"] in ("draft", "advice")
    assert data["exact"]["document"] and data["judged"]
    assert sorted(p.name for p in case.iterdir()) == ["expected.yaml", "request.md"]


@pytest.mark.parametrize("case", priced_cases(), ids=lambda c: c.name)
def test_request_does_not_give_the_answer(case):
    pricing = expected(case)["exact"]["pricing"]
    text = request(case)
    for key in ("subtotal", "markup_total", "total"):
        amount = f"{Decimal(pricing[key]):,.2f}"
        assert amount not in text and amount.removesuffix(".00") not in text


@pytest.mark.parametrize("case", priced_cases(), ids=lambda c: c.name)
def test_pricing_arithmetic(case):
    pricing = expected(case)["exact"]["pricing"]
    for line in pricing["lines"]:
        if "hours" in line:
            assert Decimal(line["hours"]) * Decimal(line["rate"]) == Decimal(line["amount"])
    subtotal = sum(Decimal(line["amount"]) for line in pricing["lines"])
    assert subtotal == Decimal(pricing["subtotal"])
    for component in pricing["markup"]:
        assert cents(subtotal * Decimal(component["percent"]) / 100) == Decimal(component["amount"])
    markup = sum(Decimal(c["amount"]) for c in pricing["markup"])
    assert markup == Decimal(pricing["markup_total"])
    passed_through = sum(Decimal(p["amount"]) for p in pricing["pass_through"])
    assert subtotal + markup + passed_through == Decimal(pricing["total"])


def test_company_pricing_comparison_in_case_4():
    exact = expected(CASES[3])["exact"]
    pricing, company = exact["pricing"], exact["explains_difference"]
    subtotal = Decimal(pricing["subtotal"])
    permit = Decimal(pricing["pass_through"][0]["amount"])
    assert cents(subtotal * (1 + Decimal(company["company_markup_percent"]) / 100) + permit) == Decimal(company["company_pricing_total"])


def test_nte_context_in_case_3():
    nte = expected(CASES[2])["exact"]["nte_context"]
    assert Decimal(nte["spent"]) / Decimal(nte["ceiling"]) * 100 == Decimal(nte["percent"])
    assert Decimal(nte["percent"]) > Decimal(nte["notice_point"])


def test_allowance_in_case_5():
    allowance = expected(CASES[4])["exact"]["allowance"]
    assert Decimal(allowance["amount"]) - Decimal(allowance["selected"]) == Decimal(allowance["under"])


needs_corpus = pytest.mark.skipif(not (CORPUS / "docs").is_dir(), reason="corpus not found; set CORPUS")


def citations():
    return [(c.name, item) for c in CASES for item in expected(c)["exact"].get("citations", [])]


@needs_corpus
@pytest.mark.parametrize("name,citation", citations(), ids=lambda v: v if isinstance(v, str) else v["id"])
def test_citation_resolves(name, citation):
    target = citation["id"]
    policy = next((CORPUS / "docs").glob("POL-01_*.md")).read_text()
    if re.search(rf"^### \d+\. {re.escape(target)} —", policy, re.M):
        return
    files = list((CORPUS / "docs").glob(f"{target}_*.md"))
    assert files, f"{target} isn't a rule or a document"
    if "section" in citation:
        text = files[0].read_text()
        assert re.search(rf"^#+ (Section )?{re.escape(citation['section'])}[. ]", text, re.M), \
            f"{target} has no section {citation['section']}"


@needs_corpus
@pytest.mark.parametrize("case", priced_cases(), ids=lambda c: c.name)
def test_company_values_match_the_package(case):
    config = CORPUS / "company" / "config.yaml"
    if not config.exists():
        pytest.skip("this corpus branch has no company/config.yaml")
    values = yaml.safe_load(config.read_text())["values"]
    rates = yaml.safe_load((CORPUS / "company/pricing/rates.yaml").read_text())["labor_billing_rates"]
    carpenter = next(r["rate"] for r in rates if r["role"] == "Carpenter")
    pricing = expected(case)["exact"]["pricing"]
    for line in pricing["lines"]:
        if "rate" in line:
            assert Decimal(line["rate"]) == Decimal(carpenter)
    if expected(case)["id"] == 1:
        structure = [(m["name"], Decimal(m["rate"])) for m in values["MARKUP-STRUCTURE"]]
        assert structure == [(m["name"], Decimal(m["percent"])) for m in pricing["markup"]]
    else:
        company = expected(case)["exact"]["explains_difference"]["company_markup_percent"]
        assert sum(Decimal(m["rate"]) for m in values["MARKUP-STRUCTURE"]) == Decimal(company)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_grade_the_pipeline_response(case):
    pytest.skip("the drafting pipeline doesn't exist yet (build step 5)")

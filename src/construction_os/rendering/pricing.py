"""Computes the numbers a PCO shows, with Decimal arithmetic rounded to cents per line and per component.

The minimum the renderer needs. Build step 4 adds the evidence interface and general conditions.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
PERMITS = "permits_and_fees"


def cents(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Component:
    name: str
    rate: Decimal
    amount: Decimal
    client_visible: bool = True


@dataclass
class Priced:
    amounts: list          # one per cost line; None when a quantity or price is unknown
    subtotal: Decimal
    components: list
    markup: Decimal
    pass_through: Decimal
    total: Decimal
    complete: bool
    contract_reference: str | None
    pass_through_categories: list


def known_number(field):
    return Decimal(str(field["value"])) if field.get("status") == "known" else None


def line_amount(line):
    quantity, price = known_number(line["quantity"]), known_number(line["unit_price"])
    return None if quantity is None or price is None else cents(quantity * price)


def price(draft, values, use_contract=True):
    terms = draft.get("contract_terms") or {}
    from_contract = use_contract and terms.get("status") == "known"
    if from_contract:
        structure = [{**m, "client_visible": True} for m in terms["markup"]]
        pass_categories = list(terms["pass_through"])
    else:
        structure = values["MARKUP-STRUCTURE"]
        pass_categories = [PERMITS] if values.get("PERMIT-TREATMENT") == "pass_through_after_markup" else []
    lines = draft["cost_lines"]
    amounts = [line_amount(line) for line in lines]
    known = [(line["category"], a) for line, a in zip(lines, amounts) if a is not None]
    marked = [(c, a) for c, a in known if c not in pass_categories]
    subtotal = sum((a for _, a in marked), Decimal("0.00"))
    components = []
    for item in structure:
        scope = item["applies_to"]
        base = subtotal if "all" in scope else sum((a for c, a in marked if c in scope), Decimal("0.00"))
        rate = Decimal(str(item["rate"]))
        components.append(Component(item["name"], rate, cents(base * rate / 100), item.get("client_visible", True)))
    markup = sum((c.amount for c in components), Decimal("0.00"))
    passed = sum((a for c, a in known if c in pass_categories), Decimal("0.00"))
    return Priced(amounts, subtotal, components, markup, passed, subtotal + markup + passed,
                  all(a is not None for a in amounts), terms["reference"] if from_contract else None, pass_categories)

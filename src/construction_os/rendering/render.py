"""Render a structured PCO draft into the company's Word template. Flags never block the output."""
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from docx import Document
from docx.shared import Inches
from docxtpl import DocxTemplate, InlineImage
from jinja2 import Environment, StrictUndefined

from .pricing import price

TO_CONFIRM = "To be confirmed"
NOT_APPLICABLE = "Not applicable"
PLACEHOLDER = "PLACEHOLDER"
LINEN, WHITE = "F5F2EE", "FFFFFF"
SIGNATURE_ORDER = {
    "before_client": ["executive_cosign", "client", "contractor_pm"],
    "after_client": ["client", "executive_cosign", "contractor_pm"],
}
SIGNER_LABELS = {"executive_cosign": "Executive co-signature", "client": "Client",
                 "contractor_pm": "Prepared by"}
HEADER_FIELDS = [("PCO number", "pco_number"), ("Date", "date"), ("Project", "project"), ("Address", "project_address"),
                 ("Client", "owner"), ("Contract", "contract_reference"), ("Change event", "change_event_ref"),
                 ("Location", "location"), ("Trades", "trades"), ("Decision needed by", "requested_approval_date"),
                 ("Change type", "cause_category")]
DATE_FIELDS = {"date", "requested_approval_date"}
BASIS_LABELS = {"hours_x_rate": "Hours × rate", "quote": "Quote", "estimate": "Estimate",
                "rate_x_duration": "Rate × duration", "weeks_x_rate": "Weeks × rate", "actual_fee": "Actual fee"}


@dataclass
class Flag:
    kind: str
    message: str


@dataclass
class RenderResult:
    path: Path
    flags: list = field(default_factory=list)
    priced: object = None

    def kinds(self):
        return {flag.kind for flag in self.flags}


def money(value):
    return f"${value:,.2f}"


def shown(field_value):
    status = field_value.get("status")
    if status == "known":
        value = field_value["value"]
        return ", ".join(value) if isinstance(value, list) else str(value)
    return TO_CONFIRM if status == "unknown" else NOT_APPLICABLE


class Needs:
    """Everything unconfirmed: flagged for the PM and listed in the box at the top of the draft."""

    def __init__(self):
        self.flags = []
        self.items = []

    def add(self, label, question, kind="missing_input"):
        self.flags.append(Flag(kind, f"{label}: {question}"))
        item = f"{label}: {question}"
        if item not in self.items:
            self.items.append(item)

    def check(self, label, field_value):
        if field_value.get("status") == "unknown":
            self.add(label, field_value["question"])


def long_date(value):
    when = date.fromisoformat(value)
    return f"{when:%B} {when.day}, {when.year}"


def shown_date(field_value):
    return long_date(field_value["value"]) if field_value.get("status") == "known" else shown(field_value)


def known_items(field_value, needs, label, empty):
    needs.check(label, field_value)
    if field_value.get("status") == "known":
        return list(field_value["value"]) or [empty]
    return [TO_CONFIRM]


def parse_days(duration):
    number, unit = duration.split()
    return int(number) * {"day": 1, "week": 7}[unit.rstrip("s")]


def quantity_text(field_value):
    return f"{field_value['value']:g}" if field_value.get("status") == "known" else TO_CONFIRM


def validity(draft, values):
    period = values["PCO-VALIDITY"]
    when = draft["header"]["date"]
    if when.get("status") != "known":
        return period, TO_CONFIRM
    end = date.fromisoformat(when["value"]) + timedelta(days=parse_days(period))
    return period, long_date(end.isoformat())


def presentation(draft, values, flags):
    setting = values["MARKUP-PRESENTATION"]
    chosen = draft["markup_presentation"]
    if chosen["source"] == "contract_term":
        return chosen["value"]
    if chosen["value"] != setting:
        flags.append(Flag("markup_presentation", f"The draft says {chosen['value']}, but the company setting is "
                                                 f"{setting}. Used the setting."))
    return setting


def price_field(line):
    field_value = line["unit_price"]
    return field_value["value"] if field_value.get("status") == "known" else None


def line_source(line):
    reference = line["evidence"]["reference"]
    label = BASIS_LABELS[line["basis"]]
    return f"{label}: {reference['value']}" if reference.get("status") == "known" else label


def line_attachment(line):
    field_value = line["attachment"]
    return field_value["value"] if field_value.get("status") == "known" else ""


def pricing_rows(draft, priced, mode):
    lines = []
    for index, (line, amount) in enumerate(zip(draft["cost_lines"], priced.amounts)):
        hide = mode == "hidden" and line["category"] not in priced.pass_through_categories
        division = line["division"]
        lines.append({
            "division": division["value"] if division.get("status") == "known" else "",
            "description": line["description"],
            "source": line_source(line),
            "attachment": line_attachment(line),
            "quantity": quantity_text(line["quantity"]),
            "unit": shown(line["unit"]),
            "unit_price": "Included" if hide else (money(price_field(line)) if price_field(line) is not None else TO_CONFIRM),
            "amount": "Included" if hide else (money(amount) if amount is not None else TO_CONFIRM),
            "fill": LINEN if index % 2 else WHITE,
        })
    rows = []
    if mode != "hidden":
        rows.append(("Subtotal", priced.subtotal))
    if mode == "itemized":
        rows += [(f"{c.name} ({c.rate:g}%)", c.amount) for c in priced.components if c.client_visible]
        rest = sum(c.amount for c in priced.components if not c.client_visible)
        if rest:
            rows.append(("Markup", rest))
    elif mode == "combined":
        rows.append(("Markup", priced.markup))
    if priced.pass_through and mode != "hidden":
        rows.append(("Permits and fees, passed through without markup", priced.pass_through))
    total = money(priced.total) if priced.complete else TO_CONFIRM
    summary = [{"label": label, "amount": money(amount), "fill": WHITE} for label, amount in rows]
    summary.append({"label": "Total", "amount": total, "fill": LINEN})
    return lines, summary


def join_names(names):
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def markup_basis(draft, priced, mode, company_name):
    """How the markup is calculated. Says "contract" only when a contract term was supplied and cited."""
    if mode == "hidden":
        return ""
    rates = join_names(f"{c.name} {c.rate:g}%" for c in priced.components)
    if priced.contract_reference:
        sentence = f"Markup per {priced.contract_reference}: {rates}, each calculated on the direct-cost subtotal, not compounded."
    else:
        owner = f"{company_name}'" if company_name.endswith("s") else f"{company_name}'s"
        sentence = f"Markup per {owner} standard pricing: {rates}, each calculated on the direct-cost subtotal."
    if priced.pass_through:
        sentence += " Permits and fees are passed through without markup."
    return sentence


def signature_rows(draft, package, flags):
    timing = package.values["AUTH-WRITTEN.cosign_timing"]
    order = SIGNATURE_ORDER[timing]
    if draft["signatures"]["order"] != order:
        flags.append(Flag("signature_order", f"The draft's signature order doesn't match {timing}. Used the setting."))
    executive = package.values["role.Executive"]["name"]
    title = package.company("signatory", "title")
    owner = draft["header"]["owner"]
    names = {
        "executive_cosign": ", ".join(x for x in (executive, title) if x),
        "client": owner["value"] if owner.get("status") == "known" else "",
        "contractor_pm": package.values["role.ProjectManager"]["name"] or "",
    }
    return [{"key": key, "label": SIGNER_LABELS[key], "name": names[key]} for key in order]


def schedule_rows(draft, needs):
    schedule = draft["schedule"]
    extension, authorization = schedule["extension_days"], schedule["authorization_by"]
    needs.check("Schedule impact", extension)
    needs.check("Critical path", schedule["critical_path"])
    needs.check("Completion date", schedule["completion_date"])
    needs.check("Authorization-by date", authorization)
    if extension.get("status") != "known":
        days = TO_CONFIRM
    elif extension["value"] == 0:
        days = "None (0 calendar days)"
    else:
        days = f"{extension['value']:g} calendar day{'' if extension['value'] == 1 else 's'} added"
    critical = schedule["critical_path"]
    if authorization.get("status") == "known":
        condition = f"Schedule assumes written authorization by {long_date(authorization['value'])}."
    elif authorization.get("status") == "unknown":
        condition = f"Schedule assumes written authorization by a date {TO_CONFIRM.lower()}."
    else:
        condition = NOT_APPLICABLE
    return {
        "days": days,
        "critical_path": critical["value"].capitalize() if critical.get("status") == "known" else TO_CONFIRM,
        "completion": shown(schedule["completion_date"]),
        "condition": condition,
    }


def clarification_lines(draft, needs):
    lines = []
    for item in draft["clarifications_and_exclusions"]:
        if item["disposition"] == "not_applicable":
            continue
        lines.append(item["text"])
        if item["disposition"] == "open_question" and item["prompt"] != "permits":
            needs.add("Clarification", item["text"])
    return lines or ["None stated"]


def check_clarifications(draft, definition, flags):
    """Every prompt for every trade. A coverage gap is a flag; it never blocks."""
    trades = {line["trade"] for line in draft["cost_lines"]}
    for prompt in definition.get("clarification_prompts") or []:
        covered = set()
        for item in draft["clarifications_and_exclusions"]:
            if item["prompt"] == prompt["id"]:
                covered |= trades if "all" in item["trades"] else set(item["trades"])
        for trade in sorted(trades - covered):
            flags.append(Flag("prompt_not_considered", f"{prompt['prompt']}: not considered for {trade}."))


def check_permits(draft, definition, needs):
    permit_trades = definition.get("permit_trades") or []
    for line in draft["cost_lines"]:
        if line["trade"] in permit_trades and line["permit"] != "included_in_quote":
            needs.add(f"{line['trade'].capitalize()} permit", "Does the quote include the permit? If not, who pulls it, and at what cost?",
                      kind="permit_question")


def check_attachment_letters(draft, flags):
    letters = {item["letter"] for item in draft["attachments"]}
    for line in draft["cost_lines"]:
        letter = line_attachment(line)
        if letter and letter not in letters:
            flags.append(Flag("attachment_letter", f"{line['description']} points to attachment {letter}, which isn't listed."))


def header_rows(draft, package, needs, valid_through):
    """Confirmed fields only. Unconfirmed ones go to the box at the top."""
    header = draft["header"]
    pairs = []
    for label, name in HEADER_FIELDS:
        field_value = header[name]
        needs.check(label, field_value)
        if field_value.get("status") == "known":
            pairs.append((label, shown_date(field_value) if name in DATE_FIELDS else shown(field_value)))
    pairs.append(("Valid through", valid_through))
    pairs.append(("Contractor", package.company("legal_name")))
    registration = package.company("licenses", "home_improvement_contractor")
    if registration:
        pairs.append(("Registration", registration))
    rows = []
    for index in range(0, len(pairs), 2):
        a = pairs[index]
        b = pairs[index + 1] if index + 1 < len(pairs) else ("", "")
        rows.append({"label_a": a[0], "value_a": a[1], "label_b": b[0], "value_b": b[1]})
    return rows


def document_text(path):
    """All text in the body, tables, headers and footers."""
    document = Document(path)
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            seen = []
            for cell in row.cells:
                if cell._tc not in seen:
                    seen.append(cell._tc)
                    parts.append(cell.text)
    for section in document.sections:
        parts += [p.text for p in section.header.paragraphs] + [p.text for p in section.footer.paragraphs]
    return "\n".join(parts)


def unfilled_fields(path):
    """Template tags left in any part of the file."""
    with zipfile.ZipFile(path) as archive:
        found = []
        for name in archive.namelist():
            if name.endswith(".xml"):
                text = re.sub(r"<[^>]+>", "", archive.read(name).decode("utf-8", "ignore"))
                found += re.findall(r"\{\{.*?\}\}|\{%.*?%\}", text)
    return found


def render(draft, package, out):
    """Fill the company's Word template from a draft. Returns the file, its flags and the computed prices."""
    needs = Needs()
    flags = needs.flags
    values = package.values
    header = draft["header"]
    priced = price(draft, values)
    mode = presentation(draft, values, flags)
    lines, summary = pricing_rows(draft, priced, mode)
    period, valid_through = validity(draft, values)
    template = DocxTemplate(package.template)
    number = header["pco_number"]
    rows = header_rows(draft, package, needs, valid_through)
    needs.check("Description", draft["description"])
    needs.check("Reason", draft["reason"])
    context = {
        "logo": InlineImage(template, str(package.logo), height=Inches(0.42)),
        "company": {"name": package.company("name")},
        "company_name_upper": package.company("name").upper(),
        "company_address": package.company("address"),
        "company_email": package.company("email"),
        "company_tagline": package.tagline,
        "generation_reference": f"Generated from package {package.reference}",
        "footer_title": f"Potential Change Order {number['value']}" if number.get("status") == "known" else "Potential Change Order",
        "header_rows": rows,
        "validity_period": period,
        "validity_date": valid_through,
        "description": shown(draft["description"]),
        "reason": shown(draft["reason"]),
        "inclusions": known_items(draft["scope"]["inclusions"], needs, "Inclusions", "None stated"),
        "deleted_scope": known_items(draft["scope"]["deleted_scope"], needs, "Deleted scope", "None"),
        "assumptions": draft["scope"]["assumptions"] or ["None stated"],
        "clarifications": clarification_lines(draft, needs),
        "lines": lines,
        "summary": summary,
        "markup_basis": markup_basis(draft, priced, mode, package.company("name")),
        "schedule": schedule_rows(draft, needs),
        "signatures": signature_rows(draft, package, flags),
        "attachments": draft["attachments"] or [{"letter": "", "description": "None"}],
    }
    for line in draft["cost_lines"]:
        for name in ("quantity", "unit", "unit_price", "division", "attachment"):
            needs.check(f"{line['description']}, {name.replace('_', ' ')}", line[name])
        needs.check(f"{line['description']}, quote reference", line["evidence"]["reference"])
        needs.check(f"{line['description']}, quote date", line["evidence"]["date"])
    check_clarifications(draft, package.definition, flags)
    check_permits(draft, package.definition, needs)
    check_attachment_letters(draft, flags)
    if not priced.complete:
        flags.append(Flag("incomplete_pricing", "A quantity or price is unknown, so the total is shown as to be confirmed."))
    if priced.contract_reference and priced.complete:
        company = price(draft, values, use_contract=False)
        flags.append(Flag("contract_pricing", f"Priced per {priced.contract_reference}: {money(priced.total)}. "
                                              f"Company pricing would give {money(company.total)}."))
    context["needed"] = needs.items
    template.render(context, Environment(undefined=StrictUndefined), autoescape=True)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    template.save(out)
    for text in document_text(out).split("\n"):
        if PLACEHOLDER in text:
            flags.append(Flag("placeholder", f"The document contains a placeholder: {text.strip()}"))
    for tag in unfilled_fields(out):
        flags.append(Flag("unfilled_field", f"A template field wasn't filled: {tag}"))
    return RenderResult(out, flags, priced)

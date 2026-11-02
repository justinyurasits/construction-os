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
                 "contractor_pm": "Contractor project manager"}
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


def shown(field_value, flags=None, name=""):
    status = field_value.get("status")
    if status == "known":
        value = field_value["value"]
        return ", ".join(value) if isinstance(value, list) else str(value)
    if status == "unknown":
        if flags is not None:
            flags.append(Flag("missing_input", f"{name}: {field_value['question']}"))
        return TO_CONFIRM
    return NOT_APPLICABLE


def long_date(value):
    when = date.fromisoformat(value)
    return f"{when:%B} {when.day}, {when.year}"


def shown_date(field_value, flags=None, name=""):
    if field_value.get("status") == "known":
        return long_date(field_value["value"])
    return shown(field_value, flags, name)


def items(field_value, flags, name, empty="None stated"):
    if field_value.get("status") == "known":
        return list(field_value["value"]) or [empty]
    return [shown(field_value, flags, name)]


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


def pricing_rows(draft, priced, mode):
    lines = []
    for index, (line, amount) in enumerate(zip(draft["cost_lines"], priced.amounts)):
        hide = mode == "hidden" and line["category"] not in priced.pass_through_categories
        lines.append({
            "description": line["description"],
            "basis": BASIS_LABELS[line["basis"]],
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


def price_field(line):
    field_value = line["unit_price"]
    return field_value["value"] if field_value.get("status") == "known" else None


def signature_rows(draft, package, flags):
    timing = package.values["AUTH-WRITTEN.cosign_timing"]
    order = SIGNATURE_ORDER[timing]
    if draft["signatures"]["order"] != order:
        flags.append(Flag("signature_order", f"The draft's signature order doesn't match {timing}. Used the setting."))
    executive = package.values["role.Executive"]["name"]
    title = package.company("signatory", "title")
    names = {
        "executive_cosign": ", ".join(x for x in (executive, title) if x),
        "client": shown(draft["header"]["owner"]),
        "contractor_pm": package.values["role.ProjectManager"]["name"] or "",
    }
    return [{"key": key, "label": SIGNER_LABELS[key], "name": names[key]} for key in order]


def schedule_text(extension):
    if extension.get("status") != "known":
        return f"{TO_CONFIRM}."
    days = extension["value"]
    if days == 0:
        return "No change to the contract time (0 calendar days)."
    return f"{days:g} calendar day{'' if days == 1 else 's'} added to the contract time."


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
    """Fill the company's template from a draft. Returns the file, its flags and the computed prices."""
    flags = []
    values = package.values
    header = draft["header"]
    priced = price(draft, values)
    mode = presentation(draft, values, flags)
    lines, summary = pricing_rows(draft, priced, mode)
    period, valid_through = validity(draft, values)
    when = header["date"]
    template = DocxTemplate(package.template)
    context = {
        "logo": InlineImage(template, str(package.logo), height=Inches(0.42)),
        "company_name_upper": package.company("name").upper(),
        "company_legal_name": package.company("legal_name"),
        "company_address": package.company("address"),
        "company_email": package.company("email"),
        "company_tagline": package.tagline,
        "company_registration": package.company("licenses", "home_improvement_contractor") or TO_CONFIRM,
        "generation_reference": f"Generated from package {package.reference}",
        "date": shown_date(when, flags, "date"),
        "validity_period": period,
        "validity_date": valid_through,
        "description": shown(draft["description"], flags, "description"),
        "reason": shown(draft["reason"], flags, "reason"),
        "inclusions": items(draft["scope"]["inclusions"], flags, "inclusions"),
        "exclusions": items(draft["scope"]["exclusions"], flags, "exclusions"),
        "assumptions": draft["scope"]["assumptions"] or ["None stated"],
        "lines": lines,
        "summary": summary,
        "pricing_note": f"Markup and pass-through per {priced.contract_reference}." if priced.contract_reference else "",
        "schedule_impact": schedule_text(draft["schedule"]["extension_days"]),
        "signatures": signature_rows(draft, package, flags),
        "attachments": draft["attachments"] or ["None"],
    }
    for name in ("pco_number", "project", "project_address", "owner", "contract_reference", "location", "trades",
                 "change_event_ref", "cause_category"):
        context[name] = shown(header[name], flags, name)
    context["requested_approval_date"] = shown_date(header["requested_approval_date"], flags, "requested_approval_date")
    for line in draft["cost_lines"]:
        for name in ("quantity", "unit", "unit_price"):
            if line[name].get("status") == "unknown":
                flags.append(Flag("missing_input", f"{line['description']}, {name}: {line[name]['question']}"))
        for name in ("reference", "date"):
            if line["evidence"][name].get("status") == "unknown":
                flags.append(Flag("missing_input", f"{line['description']}, evidence {name}: {line['evidence'][name]['question']}"))
    if draft["schedule"]["extension_days"].get("status") == "unknown":
        flags.append(Flag("missing_input", f"schedule: {draft['schedule']['extension_days']['question']}"))
    if not priced.complete:
        flags.append(Flag("incomplete_pricing", "A quantity or price is unknown, so the total is shown as to be confirmed."))
    if priced.contract_reference and priced.complete:
        company = price(draft, values, use_contract=False)
        flags.append(Flag("contract_pricing", f"Priced per {priced.contract_reference}: {money(priced.total)}. "
                                              f"Company pricing would give {money(company.total)}."))
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

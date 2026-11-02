"""Builds a plain Word template for the fictional company. Structure only: it has the same fields as a real one."""
import base64
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def loop(table, tag):
    table.add_row().cells[0].paragraphs[0].add_run(tag)


def bullets(document, name, text="{{ item }}"):
    document.add_paragraph("{%p for item in " + name + " %}")
    document.add_paragraph(text)
    document.add_paragraph("{%p endfor %}")


def build(root):
    (root / "templates/assets").mkdir(parents=True, exist_ok=True)
    (root / "templates/assets/logo.png").write_bytes(TINY_PNG)
    document = Document()
    section = document.sections[0]
    section.header.paragraphs[0].add_run("{{ logo }} {{ company_name_upper }} {{ company_address }} {{ company_email }}")
    section.footer.paragraphs[0].add_run("{{ footer_title }} {{ generation_reference }}")
    grid = document.add_table(rows=0, cols=4)
    loop(grid, "{%tr for row in header_rows %}")
    for cell, tag in zip(grid.add_row().cells, ("label_a", "value_a", "label_b", "value_b")):
        cell.text = "{{ row." + tag + " }}"
    loop(grid, "{%tr endfor %}")
    document.add_paragraph("{{ description }}")
    document.add_paragraph("Reason: {{ reason }}")
    document.add_paragraph("Included")
    bullets(document, "inclusions")
    document.add_paragraph("Deleted")
    bullets(document, "deleted_scope")
    bullets(document, "assumptions")
    bullets(document, "clarifications")
    labels = ["Div", "Description", "Source", "Att.", "Qty", "Unit", "Unit price", "Amount"]
    pricing = document.add_table(rows=1, cols=8)
    for cell, label in zip(pricing.rows[0].cells, labels):
        cell.text = label
    loop(pricing, "{%tr for line in lines %}")
    fields = ["division", "description", "source", "attachment", "quantity", "unit", "unit_price", "amount"]
    for cell, name in zip(pricing.add_row().cells, fields):
        cell.text = "{{ line." + name + " }}"
    loop(pricing, "{%tr endfor %}")
    loop(pricing, "{%tr for row in summary %}")
    row = pricing.add_row()
    row.cells[0].merge(row.cells[6]).text = "{{ row.label }}"
    row.cells[7].text = "{{ row.amount }}"
    loop(pricing, "{%tr endfor %}")
    document.add_paragraph("{{ markup_basis }}")
    schedule = document.add_table(rows=0, cols=2)
    for label, tag in (("Calendar days", "days"), ("Critical path affected", "critical_path"),
                       ("Completion date", "completion"), ("Condition", "condition")):
        cells = schedule.add_row().cells
        cells[0].text, cells[1].text = label, "{{ schedule." + tag + " }}"
    document.add_paragraph("Authorized by {{ company.name }}, valid {{ validity_period }} through {{ validity_date }}.")
    signers = document.add_table(rows=1, cols=4)
    for cell, label in zip(signers.rows[0].cells, ["Party", "Name and title", "Signature", "Date"]):
        cell.text = label
    loop(signers, "{%tr for signer in signatures %}")
    cells = signers.add_row().cells
    cells[0].paragraphs[0].add_run("{{r signer.label }}")
    cells[1].paragraphs[0].add_run("{{r signer.name }}")
    loop(signers, "{%tr endfor %}")
    bullets(document, "attachments", "☐ Attachment {{ item.letter }} — {{ item.description }}")
    document.styles["Normal"].font.name = "Arial"
    document.save(root / "templates/pco.docx")

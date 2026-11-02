import copy
import json
import os
import re
import zipfile
from pathlib import Path

import pytest
import yaml
from docx import Document

from construction_os.rendering import document_text, load_package, render, unfilled_fields
from construction_os.validate import check_draft_consistency, check_sample_draft

REPO = Path(__file__).resolve().parents[1]
CORPUS = Path(os.environ.get("CORPUS", REPO.parent / "construction-os-corpus"))
pytestmark = pytest.mark.skipif(not (CORPUS / "templates/pco.docx").exists(), reason="corpus has no PCO template")
DRAFTS = {"sample": "pco_sample_draft.json", "test1": "pco_test1_draft.json", "test4": "pco_test4_draft.json"}
TOTALS = {"sample": "$2,625.70", "test1": "$5,614.40", "test4": "$5,737.00"}


def draft(name):
    return json.loads((REPO / "samples" / DRAFTS[name]).read_text())


@pytest.fixture
def package():
    return load_package(CORPUS)


def rendered(tmp_path, package, name="sample", edit=None):
    data = draft(name)
    if edit:
        edit(data)
    return render(data, package, tmp_path / f"{name}.docx")


def table_with(path, label):
    for table in Document(path).tables:
        if table.rows[0].cells[0].text == label:
            return table
    raise AssertionError(f"no table starting {label}")


def summary_rows(path):
    table = table_with(path, "Div")
    rows = {}
    for row in table.rows[1:]:
        if row.cells[0]._tc is row.cells[6]._tc:
            rows[row.cells[0].text] = row.cells[7].text
    return rows


def needed(path):
    """The lines of the box at the top."""
    text = document_text(path).split("\n")
    if "NEEDED BEFORE SENDING" not in text:
        return []
    start = text.index("NEEDED BEFORE SENDING") + 1
    out = []
    for line in text[start:]:
        if not line.startswith("•"):
            if line.strip():
                break
            continue
        out.append(line)
    return out


def signers(path):
    return [row.cells[0].text for row in table_with(path, "Signer").rows[1:]]


# Every placeholder filled

@pytest.mark.parametrize("name", DRAFTS)
def test_every_placeholder_is_filled(tmp_path, package, name):
    result = rendered(tmp_path, package, name)
    assert unfilled_fields(result.path) == []
    assert "unfilled_field" not in result.kinds()


def test_template_has_placeholders_to_fill(package):
    assert unfilled_fields(package.template)


def test_a_missing_field_stops_the_render_instead_of_printing_blank(tmp_path, package):
    data = draft("sample")
    del data["header"]["project"]
    with pytest.raises(KeyError):
        render(data, package, tmp_path / "x.docx")


# Totals

@pytest.mark.parametrize("name", DRAFTS)
def test_total_in_the_document_matches(tmp_path, package, name):
    result = rendered(tmp_path, package, name)
    assert summary_rows(result.path)["Total"] == TOTALS[name]
    assert f"${result.priced.total:,.2f}" == TOTALS[name]


@pytest.mark.parametrize("name,folder", [("test1", "01_added_lighting"), ("test4", "04_exterior_door_contract_pricing")])
def test_document_matches_the_acceptance_case(tmp_path, package, name, folder):
    expected = yaml.safe_load((REPO / "tests/acceptance/cases" / folder / "expected.yaml").read_text())["exact"]
    pricing = expected["pricing"]
    rows = summary_rows(rendered(tmp_path, package, name).path)
    assert rows["Subtotal"] == f"${float(pricing['subtotal']):,.2f}"
    assert rows["Total"] == f"${float(pricing['total']):,.2f}"
    for component in pricing["markup"]:
        assert rows[f"{component['name']} ({component['percent']}%)"] == f"${float(component['amount']):,.2f}"


def test_contract_terms_replace_company_markup(tmp_path, package):
    result = rendered(tmp_path, package, "test4")
    text = document_text(result.path)
    rows = summary_rows(result.path)
    assert "Application fee" not in text and "Contract section 12.4" in text
    assert rows["Permits and fees, passed through without markup"] == "$200.00"
    assert any("$6,129.00" in f.message for f in result.flags if f.kind == "contract_pricing")


def test_permits_marked_up_when_the_setting_says_so(tmp_path, package):
    package.values["PERMIT-TREATMENT"] = "marked_up"
    def edit(d):
        d["contract_terms"] = {"status": "not_applicable", "reason": "None."}
    rows = summary_rows(rendered(tmp_path, package, "test4", edit).path)
    assert rows["Subtotal"] == "$5,100.00" and "Permits and fees, passed through without markup" not in rows


def test_unknown_price_shows_to_be_confirmed_and_flags(tmp_path, package):
    def edit(d):
        d["cost_lines"][0]["unit_price"] = {"status": "unknown", "question": "What's the rate?"}
    result = rendered(tmp_path, package, edit=edit)
    assert summary_rows(result.path)["Total"] == "To be confirmed"
    assert "incomplete_pricing" in result.kinds()


# Markup presentation

def test_itemized_shows_each_component(tmp_path, package):
    rows = summary_rows(rendered(tmp_path, package).path)
    assert rows["Application fee (1%)"] == "$21.70" and rows["Overhead (10%)"] == "$217.00" and rows["Fee (10%)"] == "$217.00"


def test_combined_shows_one_line(tmp_path, package):
    package.values["MARKUP-PRESENTATION"] = "combined"
    result = rendered(tmp_path, package, edit=lambda d: d["markup_presentation"].update(value="combined"))
    rows = summary_rows(result.path)
    assert rows["Markup"] == "$455.70" and "Overhead (10%)" not in rows and rows["Total"] == "$2,625.70"


def test_hidden_shows_only_the_total(tmp_path, package):
    package.values["MARKUP-PRESENTATION"] = "hidden"
    result = rendered(tmp_path, package, edit=lambda d: d["markup_presentation"].update(value="hidden"))
    text = document_text(result.path)
    assert summary_rows(result.path) == {"Total": "$2,625.70"}
    assert "Included" in text and "$720.00" not in text


def test_component_not_visible_rolls_into_markup(tmp_path, package):
    package.values["MARKUP-STRUCTURE"][0]["client_visible"] = False
    rows = summary_rows(rendered(tmp_path, package).path)
    assert rows["Markup"] == "$21.70" and "Application fee (1%)" not in rows and rows["Total"] == "$2,625.70"


def test_draft_that_differs_from_the_setting_uses_the_setting_and_flags(tmp_path, package):
    result = rendered(tmp_path, package, edit=lambda d: d["markup_presentation"].update(value="combined"))
    assert "Overhead (10%)" in summary_rows(result.path) and "markup_presentation" in result.kinds()


def test_contract_term_sets_the_presentation(tmp_path, package):
    def edit(d):
        d["markup_presentation"] = {"value": "combined", "source": "contract_term",
                                    "reference": {"status": "known", "value": "Contract 7.2"}}
    result = rendered(tmp_path, package, edit=edit)
    assert "Markup" in summary_rows(result.path) and "markup_presentation" not in result.kinds()


# Signature order

def test_signatures_before_client(tmp_path, package):
    path = rendered(tmp_path, package).path
    assert signers(path) == ["Executive co-signature", "Client", "Prepared by"]


def test_signatures_follow_the_setting_when_after_client(tmp_path, package):
    package.values["AUTH-WRITTEN.cosign_timing"] = "after_client"
    result = rendered(tmp_path, package)
    assert signers(result.path) == ["Client", "Executive co-signature", "Prepared by"]
    assert "signature_order" in result.kinds()


# PLACEHOLDER flag

def test_placeholder_flag_fires_and_does_not_block(tmp_path, package):
    result = rendered(tmp_path, package)
    assert result.path.exists()
    assert any("PLACEHOLDER" in f.message for f in result.flags if f.kind == "placeholder")


def test_no_placeholder_flag_when_the_profile_is_real(tmp_path, package):
    package.profile = copy.deepcopy(package.profile)
    package.profile["company"]["licenses"]["home_improvement_contractor"] = "HIC-123456"
    assert "placeholder" not in rendered(tmp_path, package).kinds()


# Identity, unknowns and brand

def test_identity_comes_from_the_profile(tmp_path, package):
    package.profile = copy.deepcopy(package.profile)
    package.profile["company"].update(name="Other Builders", legal_name="Other Builders Inc.", address="1 Main St.")
    text = document_text(rendered(tmp_path, package).path)
    assert "OTHER BUILDERS" in text and "Other Builders Inc." in text and "1 Main St." in text
    assert "Beacon" not in text.replace("BEACON", "Beacon") and "Linwood" not in text


def test_template_has_no_identity_typed_in(package):
    with zipfile.ZipFile(package.template) as archive:
        text = "".join(archive.read(n).decode("utf-8", "ignore") for n in archive.namelist() if n.endswith(".xml"))
    for word in ("Beacon", "BEACON", "Linwood", "Yurasits", "Medford"):
        assert word not in text


def test_unknowns_are_flagged_never_invented(tmp_path, package):
    result = rendered(tmp_path, package, "test1")
    assert any("Who is the client?" in f.message for f in result.flags if f.kind == "missing_input")


def test_unconfirmed_header_fields_move_to_the_needed_box(tmp_path, package):
    path = rendered(tmp_path, package, "test1").path
    table = Document(path).tables[0]
    grid = "\n".join(cell.text for row in table.rows for cell in row.cells)
    assert "Client" not in grid and "To be confirmed" not in grid and "Date" in grid
    assert any(line.startswith("•  Client: Who is the client?") for line in needed(path))


def test_no_needed_box_when_everything_is_confirmed(tmp_path, package):
    package.values["MARKUP-PRESENTATION"] = "itemized"
    def edit(d):
        known = {"status": "known", "value": "Known"}
        for name, value in d["header"].items():
            if value["status"] == "unknown":
                d["header"][name] = {"status": "known", "value": "2026-11-30"} if name == "requested_approval_date" else known
        d["schedule"]["authorization_by"] = {"status": "known", "value": "2026-11-20"}
        d["clarifications_and_exclusions"] = [i for i in d["clarifications_and_exclusions"] if i["disposition"] != "open_question"]
        for line in d["cost_lines"]:
            line["evidence"]["date"] = {"status": "known", "value": "2026-11-01"}
            line["permit"] = "included_in_quote" if line["trade"] == "electrical" else line["permit"]
    assert needed(rendered(tmp_path, package, "test1", edit).path) == []


# New sections

def test_clarifications_show_and_skip_not_applicable(tmp_path, package):
    text = document_text(rendered(tmp_path, package, "test1").path)
    assert "Concealed conditions found on opening" in text and "No permit for this trade" not in text


def test_every_prompt_for_every_trade_is_checked(tmp_path, package):
    def edit(d):
        d["clarifications_and_exclusions"] = [i for i in d["clarifications_and_exclusions"] if i["prompt"] != "hazardous_materials"]
    flags = [f.message for f in rendered(tmp_path, package, "test1", edit).flags if f.kind == "prompt_not_considered"]
    assert any("Hazardous materials: not considered for electrical" in m for m in flags)


def test_prompts_all_considered_in_the_samples(tmp_path, package):
    for name in DRAFTS:
        assert "prompt_not_considered" not in rendered(tmp_path, package, name).kinds()


def test_deleted_scope_none(tmp_path, package):
    text = document_text(rendered(tmp_path, package, "test1").path).split("\n")
    assert "•  None" in text[text.index("Deleted") + 1]


def test_permit_trade_raises_a_question(tmp_path, package):
    result = rendered(tmp_path, package, "test1")
    assert any("Electrical permit" in f.message for f in result.flags if f.kind == "permit_question")
    assert any("Electrical permit" in line for line in needed(result.path))


def test_no_permit_question_when_the_quote_includes_it(tmp_path, package):
    def edit(d):
        d["cost_lines"][0]["permit"] = "included_in_quote"
    assert "permit_question" not in rendered(tmp_path, package, "test1", edit).kinds()


def test_non_permit_trade_raises_no_question(tmp_path, package):
    def edit(d):
        d["cost_lines"] = [line for line in d["cost_lines"] if line["trade"] != "electrical"]
    assert "permit_question" not in rendered(tmp_path, package, "test1", edit).kinds()


def test_pricing_line_has_division_quote_and_letter(tmp_path, package):
    table = table_with(rendered(tmp_path, package, "test1").path, "Div")
    first = [cell.text for cell in table.rows[1].cells]
    assert first[0] == "26" and "Electrical subcontractor quote" in first[2] and first[3] == "A"


def test_line_pointing_to_a_missing_attachment_is_flagged(tmp_path, package):
    def edit(d):
        d["cost_lines"][0]["attachment"] = {"status": "known", "value": "Z"}
    assert "attachment_letter" in rendered(tmp_path, package, "test1", edit).kinds()


def test_attachments_checklist_has_letters(tmp_path, package):
    text = document_text(rendered(tmp_path, package, "test1").path)
    assert "☐  Attachment A — Electrical subcontractor quote" in text and "Attachment C" in text


def test_schedule_table(tmp_path, package):
    def edit(d):
        d["schedule"]["authorization_by"] = {"status": "known", "value": "2026-11-20"}
    table = table_with(rendered(tmp_path, package, "test1", edit).path, "Calendar days")
    values = {row.cells[0].text: row.cells[1].text for row in table.rows}
    assert values["Calendar days"] == "None (0 calendar days)" and values["Critical path affected"] == "No"
    assert values["Completion date"] == "No change"
    assert values["Condition"] == "Schedule assumes written authorization by November 20, 2026."


def test_markup_sentence_cites_company_pricing_never_the_contract(tmp_path, package):
    text = document_text(rendered(tmp_path, package, "test1").path)
    assert "standard pricing: Application fee 1%, Overhead 10% and Fee 10%" in text
    assert f"{package.company('name')}'s standard" not in text or not package.company("name").endswith("s")
    assert "per the Contract" not in text and "per Contract" not in text


def test_markup_sentence_cites_a_supplied_contract(tmp_path, package):
    text = document_text(rendered(tmp_path, package, "test4").path)
    assert "Markup per Contract section 12.4: Overhead 8% and Profit 5%" in text and "standard pricing" not in text


def test_authorization_terms(tmp_path, package):
    text = document_text(rendered(tmp_path, package).path)
    assert (f"only when signed by the client and co-signed by {package.company('name')} below. "
            "Approval by email, text message or conversation does not authorize the work") in text


def test_prepared_by_has_no_authorization_wording(tmp_path, package):
    table = table_with(rendered(tmp_path, package).path, "Signer")
    assert table.rows[3].cells[0].text == "Prepared by"


def test_pricing_rows_stay_together_and_the_header_repeats(tmp_path, package):
    xml = table_with(rendered(tmp_path, package).path, "Div")._tbl.xml
    assert "w:tblHeader" in xml
    rows = table_with(rendered(tmp_path, package).path, "Div").rows
    for row in rows:
        assert all(p.paragraph_format.keep_with_next for cell in row.cells for p in cell.paragraphs)


def test_zero_schedule_impact_is_stated(tmp_path, package):
    table = table_with(rendered(tmp_path, package).path, "Calendar days")
    assert table.rows[0].cells[1].text == "None (0 calendar days)"


def test_validity_date_is_thirty_days_from_the_pco_date(tmp_path, package):
    text = document_text(rendered(tmp_path, package).path)
    assert "valid for 30 days" in text and "December 2, 2026" in text


def test_terms_state_the_billing_gate(tmp_path, package):
    text = document_text(rendered(tmp_path, package).path)
    assert "not billable until the prime contract change order is executed" in text


def test_georgia_is_the_only_typeface(tmp_path, package):
    with zipfile.ZipFile(rendered(tmp_path, package).path) as archive:
        xml = "".join(archive.read(n).decode() for n in archive.namelist()
                      if re.match(r"word/(document|header\d*|footer\d*)\.xml", n))
    assert set(re.findall(r'w:ascii="([^"]+)"', xml)) == {"Georgia"}


@pytest.mark.parametrize("name", DRAFTS)
def test_sample_drafts_are_valid_and_consistent(name):
    path = REPO / "samples" / DRAFTS[name]
    assert check_sample_draft(path).passed
    assert check_draft_consistency(CORPUS, path).passed

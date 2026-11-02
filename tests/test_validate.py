import json
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import write_entry
from construction_os import validate as v


def errors(result):
    return "\n".join(result.errors)


def replace(path: Path, old, new):
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def test_valid_package_passes(corpus):
    results = v.run_checks(corpus)
    assert [r.name for r in results if not r.passed] == []


# registry_entries

def test_registry_fails_on_missing_field(corpus):
    replace(corpus / "registry/NTE-CHECKPOINTS.yaml", "change_approver: Policy Owner\n", "")
    result = v.check_registry_entries(corpus)
    assert not result.passed and "change_approver" in errors(result)


def test_registry_fails_on_bad_kind(corpus):
    replace(corpus / "registry/NTE-CHECKPOINTS.yaml", "kind: parameter", "kind: setting")
    assert not v.check_registry_entries(corpus).passed


def test_registry_fails_when_id_differs_from_file_name(corpus):
    replace(corpus / "registry/NTE-CHECKPOINTS.yaml", "id: NTE-CHECKPOINTS", "id: OTHER")
    assert "doesn't match the file name" in errors(v.check_registry_entries(corpus))


def test_registry_fails_on_unknown_constraint(corpus):
    write_entry(corpus, "EXTRA", vt="percent", schema="percent", default="5", constraints="{ceiling: 10}")
    assert "unknown constraint" in errors(v.check_registry_entries(corpus))


def test_registry_fails_when_default_breaks_schema(corpus):
    write_entry(corpus, "EXTRA", vt="percent", schema="percent", default="500", constraints="{}")
    assert "is not a percent" in errors(v.check_registry_entries(corpus))


def test_registry_reports_invalid_yaml_without_crashing(corpus):
    (corpus / "registry/NTE-CHECKPOINTS.yaml").write_text("id: [unclosed\n")
    results = {r.name: r for r in v.run_checks(corpus)}
    assert "not valid YAML" in errors(results["registry_entries"])
    assert results["sample_draft"].passed


def test_unreadable_config_fails_its_check_only(corpus):
    (corpus / "company/config.yaml").write_text("values: [unclosed\n")
    results = {r.name: r for r in v.run_checks(corpus)}
    assert not results["config_values"].passed and results["registry_entries"].passed


# config_values

@pytest.mark.parametrize("old,new,message", [
    ("notify_at: 70, stop_at: 90", "notify_at: seventy, stop_at: 90", "is not a percent"),
    ("notify_at: 70, stop_at: 90", "notify_at: 40, stop_at: 90", "below the minimum"),
    ("notify_at: 70, stop_at: 90", "notify_at: 90, stop_at: 80", "breaks the rule"),
    ("CE-OPEN-WINDOW: 48 hours", "CE-OPEN-WINDOW: soon", "is not a duration"),
    ("CE-OPEN-WINDOW: 48 hours", "OTHER: 48 hours", "not in the registry"),
    ("key: rates", "key: nothing", "has no 'nothing'"),
])
def test_config_fails(corpus, old, new, message):
    replace(corpus / "company/config.yaml", old, new)
    result = v.check_config_values(corpus)
    assert not result.passed and message in errors(result)


def test_config_fails_on_duplicate_rate_role(corpus):
    (corpus / "company/pricing/rates.yaml").write_text(
        "rates:\n  - {role: Carpenter, rate: 90}\n  - {role: Carpenter, rate: 95}\n")
    assert "duplicate role" in errors(v.check_config_values(corpus))


def test_config_fails_when_identity_is_not_in_profile(corpus):
    (corpus / "company/profile.yaml").write_text("company: {}\n")
    assert "not in the company profile" in errors(v.check_config_values(corpus))


def test_blank_identity_field_warns_but_passes(corpus):
    write_entry(corpus, "company.licenses", kind="identity", schema='{number: "text?"}', default="null", constraints="{}")
    (corpus / "company/profile.yaml").write_text("company:\n  name: Test Builders\n  licenses:\n    number:\n")
    result = v.check_config_values(corpus)
    assert result.passed and "company.licenses.number is blank" in result.warnings[0]


def test_placeholder_warns_but_passes(corpus):
    write_entry(corpus, "company.licenses", kind="identity", schema='{number: "text?"}', default="null", constraints="{}")
    (corpus / "company/profile.yaml").write_text(
        "company:\n  name: Test Builders\n  licenses:\n    number: HIC-000000 (PLACEHOLDER)\n")
    result = v.check_config_values(corpus)
    assert result.passed and "company.licenses.number is a placeholder" in result.warnings[0]


def test_placeholder_in_a_config_value_warns(corpus):
    (corpus / "company/pricing/rates.yaml").write_text("rates:\n  - {role: PLACEHOLDER, rate: 90}\n")
    result = v.check_config_values(corpus)
    assert result.passed and "RATES[0].role is a placeholder" in result.warnings[0]


def test_config_fails_on_bad_markup_presentation(corpus):
    replace(corpus / "company/config.yaml", "MARKUP-PRESENTATION: itemized", "MARKUP-PRESENTATION: lumped")
    assert "is not one of" in errors(v.check_config_values(corpus))


def test_config_fails_on_bad_cosign_timing(corpus):
    replace(corpus / "company/config.yaml", "cosign_timing: before_client", "cosign_timing: whenever")
    assert "is not one of" in errors(v.check_config_values(corpus))


def test_hidden_presentation_with_visible_component_warns(corpus):
    write_entry(corpus, "MARKUP-STRUCTURE", vt="list", schema="{items: {name: text, client_visible: boolean}}",
                default="[]", constraints="{}")
    replace(corpus / "company/config.yaml", "MARKUP-PRESENTATION: itemized",
            "MARKUP-PRESENTATION: hidden\n  MARKUP-STRUCTURE: [{name: Fee, client_visible: true}]")
    result = v.check_config_values(corpus)
    assert result.passed and "hidden" in result.warnings[0]


# definition_dependencies

@pytest.mark.parametrize("old,new", [
    ("{id: AUTH-WRITTEN, applies_when: always}", "{id: AUTH-WRITTEN-X, applies_when: always}"),
    ("{id: FCM-03, applies_when: always}", "{id: FCM-99, applies_when: always}"),
    ("{id: NTE-CHECKPOINTS, applies_when: nte_present}", "{id: NOT-A-PARAMETER, applies_when: nte_present}"),
    ("{id: FCM-03, applies_when: always}", "{id: FCM-03}"),
    ("procedure: CHG-53", "procedure: CHG-99"),
])
def test_definition_fails(corpus, old, new):
    replace(corpus / "definitions/CHG-53-DEF.yaml", old, new)
    assert not v.check_definition_dependencies(corpus).passed


def test_missing_template_warns_but_passes(corpus):
    with open(corpus / "definitions/CHG-53-DEF.yaml", "a") as handle:
        handle.write("template: templates/pco.docx\n")
    result = v.check_definition_dependencies(corpus)
    assert result.passed and "doesn't exist yet" in result.warnings[0]


# sample_draft

def test_real_sample_passes():
    assert v.check_sample_draft().passed


@pytest.mark.parametrize("change", [
    lambda d: d["cost_lines"][0].pop("evidence"),
    lambda d: d["cost_lines"][0].update(category="overhead"),
    lambda d: d["cost_lines"][0].update(quantity=None),
    lambda d: d["cost_lines"][0]["evidence"].pop("date"),
    lambda d: d.pop("reason"),
    lambda d: d["schedule"].update(extension_days={"status": "known", "value": -1}),
    lambda d: d.update(reason={"status": "unknown"}),
])
def test_sample_fails(tmp_path, change):
    draft = json.loads(v.SAMPLE_DRAFT.read_text())
    change(draft)
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(draft))
    assert not v.check_sample_draft(path).passed


def test_sample_matches_the_worked_example():
    """Design section 6: subtotal $2,170, markup $455.70, total $2,625.70."""
    draft = json.loads(v.SAMPLE_DRAFT.read_text())
    subtotal = sum(Decimal(str(line["quantity"]["value"])) * Decimal(str(line["unit_price"]["value"]))
                   for line in draft["cost_lines"])
    markup = subtotal * Decimal("0.21")
    assert (subtotal, markup, subtotal + markup) == (Decimal(2170), Decimal("455.70"), Decimal("2625.70"))


# draft_consistency

def edited_sample(tmp_path, change):
    draft = json.loads(v.SAMPLE_DRAFT.read_text())
    change(draft)
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(draft))
    return path


def test_consistency_passes_on_the_sample(corpus):
    assert v.check_draft_consistency(corpus).passed


def test_draft_signature_order_is_flagged(corpus, tmp_path):
    path = edited_sample(tmp_path, lambda d: d["signatures"].update(order=["client", "executive_cosign", "contractor_pm"]))
    assert "draft signature order" in errors(v.check_draft_consistency(corpus, path))


def test_setting_after_client_flags_the_definition_and_draft(corpus):
    replace(corpus / "company/config.yaml", "cosign_timing: before_client", "cosign_timing: after_client")
    message = errors(v.check_draft_consistency(corpus))
    assert "CHG-53-DEF" in message and "draft signature order" in message


def test_draft_markup_presentation_must_match_the_setting(corpus, tmp_path):
    path = edited_sample(tmp_path, lambda d: d["markup_presentation"].update(value="combined"))
    assert "no contract term is cited" in errors(v.check_draft_consistency(corpus, path))


def contract_term(draft):
    draft["markup_presentation"] = {"value": "combined", "source": "contract_term",
                                    "reference": {"status": "known", "value": "Prime Agreement 7.2"}}


def test_cited_contract_term_wins_over_the_setting(corpus, tmp_path):
    path = edited_sample(tmp_path, contract_term)
    assert v.check_draft_consistency(corpus, path).passed and v.check_sample_draft(path).passed


def test_contract_term_without_a_reference_fails_the_schema(tmp_path):
    def change(draft):
        contract_term(draft)
        draft["markup_presentation"]["reference"] = {"status": "unknown", "question": "Which clause?"}
    assert not v.check_sample_draft(edited_sample(tmp_path, change)).passed


# command

def test_main_exit_codes(corpus, capsys):
    assert v.main(["--corpus", str(corpus)]) == 0
    replace(corpus / "registry/NTE-CHECKPOINTS.yaml", "kind: parameter", "kind: setting")
    assert v.main(["--corpus", str(corpus)]) == 1
    assert "FAIL  registry_entries" in capsys.readouterr().out

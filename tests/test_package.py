"""The renderer against the real package: its sample drafts and template. All expectations come from the package."""
import json
import os
import re
import shutil
import subprocess
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from docx import Document

from construction_os.rendering import CHECKLIST_TITLE, document_text, load_package, render, render_checklist, unfilled_fields
from construction_os.validate import sample_paths

CORPUS = Path(os.environ.get("CORPUS", Path(__file__).resolve().parents[2] / "construction-os-corpus"))
pytestmark = pytest.mark.skipif(not (CORPUS / "templates/pco.docx").exists() or not (CORPUS / "samples").is_dir(),
                                reason="package not found; set CORPUS")
SOFFICE = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
SAMPLES = sample_paths(CORPUS)
money = lambda value: f"${Decimal(value):,.2f}"


@pytest.fixture
def package():
    return load_package(CORPUS)


def expectations():
    return yaml.safe_load((CORPUS / "samples/expected.yaml").read_text())


def rendered(tmp_path, package, path):
    return render(json.loads(path.read_text()), package, tmp_path / f"{path.stem}.docx")


def summary_rows(path):
    table = next(t for t in Document(path).tables if t.rows[0].cells[0].text == "Div")
    return {row.cells[0].text: row.cells[7].text for row in table.rows[1:] if row.cells[0]._tc is row.cells[6]._tc}


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_sample_renders_with_every_field_filled(tmp_path, package, path):
    assert unfilled_fields(rendered(tmp_path, package, path).path) == []


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_sample_totals_match_the_package(tmp_path, package, path):
    expected = expectations()[path.name]
    rows = summary_rows(rendered(tmp_path, package, path).path)
    assert rows["Subtotal"] == money(expected["subtotal"]) and rows["Total"] == money(expected["total"])


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_sample_has_the_required_text(tmp_path, package, path):
    text = document_text(rendered(tmp_path, package, path).path)
    for required in expectations()["required_text"]:
        assert required in text


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_sample_checklist(tmp_path, package, path):
    draft = json.loads(path.read_text())
    result = render(draft, package, tmp_path / "pco.docx")
    text = document_text(render_checklist(result, draft, package, tmp_path / "list.docx"))
    assert text.startswith(CHECKLIST_TITLE)


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_all_prompts_considered_in_the_samples(tmp_path, package, path):
    assert "prompt_not_considered" not in rendered(tmp_path, package, path).kinds()


def test_template_has_no_identity_typed_in(package):
    with zipfile.ZipFile(package.template) as archive:
        text = "".join(archive.read(n).decode("utf-8", "ignore") for n in archive.namelist() if n.endswith(".xml"))
    for value in (package.company("name"), package.company("legal_name"), package.company("address"), package.tagline):
        assert value not in text


def test_tagline_stays_out_of_the_document(tmp_path, package):
    assert package.tagline not in document_text(rendered(tmp_path, package, SAMPLES[0]).path)


def test_one_typeface(tmp_path, package):
    with zipfile.ZipFile(rendered(tmp_path, package, SAMPLES[0]).path) as archive:
        xml = "".join(archive.read(n).decode() for n in archive.namelist() if re.match(r"word/(document|header\d*|footer\d*)\.xml", n))
    assert len(set(re.findall(r'w:ascii="([^"]+)"', xml))) == 1


def test_pricing_rows_stay_together_and_the_header_repeats(tmp_path, package):
    table = next(t for t in Document(rendered(tmp_path, package, SAMPLES[0]).path).tables if t.rows[0].cells[0].text == "Div")
    assert "w:tblHeader" in table._tbl.xml
    assert all(p.paragraph_format.keep_with_next for row in table.rows for cell in row.cells for p in cell.paragraphs)


def test_terms_stay_with_the_signatures(tmp_path, package):
    document = Document(rendered(tmp_path, package, SAMPLES[0]).path)
    paragraphs = document.paragraphs
    start = next(i for i, p in enumerate(paragraphs) if p.text == "TERMS")
    end = next(i for i, p in enumerate(paragraphs) if p.text == "SIGNATURES")
    assert all(p.paragraph_format.keep_with_next for p in paragraphs[start:end + 1])
    table = next(t for t in document.tables if t.rows[0].cells[0].text == "Party")
    assert all(p.paragraph_format.keep_with_next for row in table.rows for cell in row.cells for p in cell.paragraphs)


@pytest.mark.skipif(not (Path(SOFFICE).exists() and shutil.which("pdfinfo")), reason="LibreOffice or pdfinfo not installed")
def test_package_acceptance_samples_fit_two_pages(tmp_path, package):
    from construction_os.rendering.__main__ import preview_env

    for path in SAMPLES:
        result = rendered(tmp_path, package, path)
        subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(result.path)],
                       check=True, capture_output=True, env=preview_env())
        info = subprocess.run(["pdfinfo", str(result.path.with_suffix(".pdf"))], capture_output=True, text=True).stdout
        assert int(re.search(r"Pages:\s+(\d+)", info).group(1)) <= 2, path.name

"""No company content in this repository (CLAUDE.md). Everything company-specific is read from the package."""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
# Written in pieces, so this file doesn't match itself.
FORBIDDEN = re.compile("Beacon" + r"\s+Hill|\bBH" + r"I\b", re.I)


def tracked_and_new_files():
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO, capture_output=True, text=True, check=True)
    return [REPO / name for name in out.stdout.splitlines() if (REPO / name).is_file()]


def company_mentions(text):
    return FORBIDDEN.findall(text)


def test_the_check_catches_the_name():
    assert company_mentions("Beacon" + " Hill Interiors") and company_mentions("the " + "BH" + "I default")
    assert not company_mentions("Example Builders LLC, a subhire")


def test_no_company_name_anywhere_in_the_repository():
    found = []
    for path in tracked_and_new_files():
        text = path.read_bytes().decode("utf-8", "ignore")
        if company_mentions(text) or company_mentions(path.name):
            found.append(str(path.relative_to(REPO)))
    assert not found, f"company content in: {found}"

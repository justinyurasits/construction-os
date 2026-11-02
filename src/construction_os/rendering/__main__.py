"""Render the three sample drafts, with PDF previews.

  python -m construction_os.rendering --corpus ../construction-os-corpus
"""
import argparse
import json
import shutil
import os
import subprocess
import tempfile
from pathlib import Path

from . import load_package, render

REPO = Path(__file__).resolve().parents[3]
MAC_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
SAMPLES = {"pco_sample": "pco_sample_draft.json", "pco_test1": "pco_test1_draft.json", "pco_test4": "pco_test4_draft.json"}


def preview_env():
    """Headless LibreOffice finds fonts through fontconfig, which doesn't see macOS's Georgia by default."""
    env = dict(os.environ)
    fonts = Path("/System/Library/Fonts/Supplemental")
    if fonts.exists():
        conf = Path(tempfile.gettempdir()) / "construction_os_fonts.conf"
        conf.write_text(f'<?xml version="1.0"?><fontconfig><dir>{fonts}</dir>'
                        f'<cachedir>{tempfile.gettempdir()}/construction_os_fontcache</cachedir></fontconfig>')
        env["FONTCONFIG_FILE"] = str(conf)
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out", default=str(REPO / "samples" / "rendered"))
    args = parser.parse_args()
    package = load_package(args.corpus)
    out = Path(args.out)
    soffice = shutil.which("soffice") or (MAC_SOFFICE if Path(MAC_SOFFICE).exists() else None)
    for name, draft_file in SAMPLES.items():
        draft = json.loads((REPO / "samples" / draft_file).read_text())
        result = render(draft, package, out / f"{name}.docx")
        print(f"{result.path}  total {result.priced.total}")
        for flag in result.flags:
            print(f"  FLAG {flag.kind}: {flag.message}")
        if soffice:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out), str(result.path)],
                           check=True, capture_output=True, env=preview_env())
            print(f"  {out / (name + '.pdf')}")
    if not soffice:
        print("soffice not found: no PDF previews")


if __name__ == "__main__":
    main()

"""The company package as the renderer reads it. Later this reads a published package (design section 3)."""
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from construction_os.validate import CONFIG, DEFINITION, load_yaml, resolve


@dataclass
class Package:
    root: Path
    values: dict
    profile: dict
    reference: str = "unversioned"
    definition: dict = field(default_factory=dict)

    @property
    def template(self):
        return self.root / "templates" / "pco.docx"

    @property
    def logo(self):
        return self.root / "templates" / "assets" / "logo.png"

    def company(self, *keys):
        data = self.profile.get("company") or {}
        for key in keys:
            data = (data or {}).get(key)
        return data

    @property
    def tagline(self):
        return (self.profile.get("brand") or {}).get("tagline")


def load_package(root):
    root = Path(root)
    config = load_yaml(root / CONFIG)
    profile = load_yaml(root / config["identity"]["profile"])
    errors = []
    values = {key: resolve(value, root, profile, key, errors) for key, value in (config.get("values") or {}).items()}
    if errors:
        raise ValueError("; ".join(errors))
    return Package(root, values, profile, _commit(root), load_yaml(root / DEFINITION))


def _commit(root):
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unversioned"

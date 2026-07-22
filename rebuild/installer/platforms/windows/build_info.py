"""Resolve the release tag/repo and bundled asset paths at runtime.

When packaged by PyInstaller the build writes ``build_info.json`` and bundles
the plan template alongside the code; both land under ``sys._MEIPASS``. In a
plain source checkout we fall back to environment overrides and the in-tree
template so the wizard is still driveable during development and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

DEFAULT_REPO = "lachthox/OmarchyInstaller"


@dataclass(frozen=True, slots=True)
class BuildInfo:
    release_tag: str
    release_repo: str
    producer_version: str
    template_path: Path

    @property
    def can_provision(self) -> bool:
        return bool(self.release_tag) and self.template_path.is_file()


def _bundle_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # rebuild/installer/platforms/windows/build_info.py -> rebuild/
    return Path(__file__).resolve().parents[3]


def _template_path(root: Path) -> Path:
    # Both frozen (_MEIPASS) and source layouts place the template under
    # rebuild/assets/templates; _bundle_root already resolves the right base.
    return root / "assets" / "templates" / "plan.template.json"


def load_build_info() -> BuildInfo:
    root = _bundle_root()
    data: dict[str, str] = {}
    info_file = root / "build_info.json"
    if info_file.is_file():
        try:
            loaded = json.loads(info_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = {str(k): str(v) for k, v in loaded.items()}
        except (OSError, ValueError):
            data = {}

    tag = os.environ.get("OMARCHY_RELEASE_TAG", "") or data.get("release_tag", "")
    repo = os.environ.get("OMARCHY_RELEASE_REPO", "") or data.get("release_repo", "") or DEFAULT_REPO
    producer = data.get("producer_version", "") or "1.0.0"
    template = _template_path(root)
    return BuildInfo(
        release_tag=tag,
        release_repo=repo,
        producer_version=producer,
        template_path=template,
    )

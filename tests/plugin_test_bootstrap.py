from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PLUGIN_NAME = "astrbot_plugin_local_action"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def ensure_plugin_package() -> None:
    if PLUGIN_NAME in sys.modules:
        return

    spec = importlib.util.spec_from_file_location(
        PLUGIN_NAME,
        PLUGIN_ROOT / "__init__.py",
        submodule_search_locations=[str(PLUGIN_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {PLUGIN_NAME} from {PLUGIN_ROOT}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[PLUGIN_NAME] = module
    spec.loader.exec_module(module)


ensure_plugin_package()

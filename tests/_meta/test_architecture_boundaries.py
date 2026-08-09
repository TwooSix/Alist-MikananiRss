import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "openlist_ani"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(f"{'.' * node.level}{node.module}")
    return names


def _py_files(path: Path) -> list[Path]:
    return [item for item in path.rglob("*.py") if "__pycache__" not in item.parts]


def test_domain_depends_only_on_standard_library_and_itself():
    violations = []
    for path in _py_files(SRC / "domain"):
        for imported in _imports(path):
            if imported.startswith("."):
                continue
            root = imported.split(".", 1)[0]
            if root in sys.stdlib_module_names or imported.startswith(
                "openlist_ani.domain"
            ):
                continue
            violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert violations == []


def test_application_does_not_import_adapters_or_bootstrap():
    forbidden = ("openlist_ani.adapters", "openlist_ani.bootstrap")
    violations = []
    for path in _py_files(SRC / "application"):
        for imported in _imports(path):
            if imported.startswith(forbidden):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert violations == []


def test_removed_transition_directories_cannot_reappear():
    forbidden = [
        "adapters/inbound",
        "adapters/outbound",
        "application/anime_library_ingestion",
        "domain/anime_release",
        "domain/download_task",
        "integrations/llm",
        "integrations/openlist",
        "utils",
    ]
    assert [item for item in forbidden if (SRC / item).exists()] == []


def test_removed_outbound_import_path_cannot_reappear():
    violations = []
    for path in _py_files(SRC):
        relative = path.relative_to(SRC)
        for imported in _imports(path):
            if imported.startswith("openlist_ani.adapters.outbound"):
                violations.append(f"{relative} imports {imported}")
    assert violations == []


def test_adapter_registry_is_the_only_core_registry():
    registry_classes = []
    for path in _py_files(SRC):
        relative = path.relative_to(SRC)
        if relative.parts[0] in {"assistant", "builtin_skills"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Registry"):
                registry_classes.append((relative.as_posix(), node.name))
    assert registry_classes == [("adapters/registry.py", "AdapterRegistry")]


def test_legacy_migration_type_is_private_and_not_imported_by_runtime():
    for path in _py_files(SRC):
        if path.name == "legacy_v1_import.py":
            continue
        assert "_LegacyTask" not in path.read_text(encoding="utf-8")

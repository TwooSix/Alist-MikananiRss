from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_core_uses_the_converged_four_layer_directory_structure():
    src = ROOT / "src" / "openlist_ani"
    assert {"bootstrap", "adapters", "application", "domain"} <= {
        path.name for path in src.iterdir() if path.is_dir()
    }
    for path in (
        "adapters/configuration",
        "adapters/persistence",
        "adapters/feed_sources",
        "adapters/metadata_sources",
        "adapters/download_backends/openlist",
        "adapters/notifications",
        "adapters/torrent",
        "adapters/http",
        "integrations/messaging",
    ):
        assert (src / path).is_dir(), path

    for path in (
        "backend",
        "core",
        "composition",
        "interfaces",
        "infrastructure",
    ):
        assert not (src / path).exists(), path

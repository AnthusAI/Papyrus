from __future__ import annotations

import os

import pytest

import wheel_support as support


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    return support.build_wheel(tmp_path_factory.mktemp("wheel"))


def test_every_default_config_the_code_names_is_packaged_next_to_its_corpora_source():
    named = support.runtime_default_corpora_names()
    assert "papyrus-semantic-relation-types.yml" in named
    packaged = {path.name for path in support.SOURCE_DIRECTORY.iterdir()}
    assert named <= packaged, f"defaults named in code but not under {support.SOURCE_DIRECTORY}: {sorted(named - packaged)}"


def test_the_corpora_directory_serves_the_packaged_files_so_there_is_one_copy():
    for path in support.SOURCE_DIRECTORY.iterdir():
        served = support.REPO_ROOT / "corpora" / path.name
        assert served.resolve() == path.resolve()


def test_the_built_wheel_contains_every_runtime_data_file(wheel):
    members = support.wheel_members(wheel)
    expected = {f"{support.PACKAGED_DIRECTORY}/{path.name}" for path in support.SOURCE_DIRECTORY.iterdir()}
    assert expected <= members, f"missing from the wheel: {sorted(expected - members)}"
    assert f"{support.PACKAGED_DIRECTORY}/papyrus-semantic-relation-types.yml" in members
    for name in support.runtime_default_corpora_names():
        assert f"{support.PACKAGED_DIRECTORY}/{name}" in members


def test_the_loader_finds_the_data_when_run_from_an_installed_package(wheel, tmp_path):
    target = tmp_path / "site-packages"
    support.install_wheel(wheel, target)
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    environment = {key: value for key, value in os.environ.items() if key not in {"PAPYRUS_ROOT", "PYTHONPATH"}}
    code = (
        "from pathlib import Path\n"
        "import papyrus_content\n"
        "from papyrus_content import relation_types, newsroom_doctrine, cloud_procedures\n"
        "from papyrus_content.env import PAPYRUS_ROOT\n"
        f"assert Path(papyrus_content.__file__).resolve().is_relative_to(Path({str(target)!r}).resolve()), papyrus_content.__file__\n"
        "assert not (PAPYRUS_ROOT / 'corpora').exists(), PAPYRUS_ROOT\n"
        "path = relation_types.DEFAULT_RELATION_TYPES_PATH\n"
        "assert path.is_file() and 'site-packages' in str(path), path\n"
        "assert len(relation_types.load_semantic_relation_type_seeds()) > 0\n"
        "assert newsroom_doctrine.DEFAULT_PUBLICATION_DOCTRINE_PATH.is_file()\n"
        "assert cloud_procedures.REQUIRED_PROCEDURES_CONFIG_PATH.is_file()\n"
        "print('ok')\n"
    )
    result = support.run_installed(target, workdir, code, environment)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_a_checkout_still_prefers_the_repo_corpora_file(tmp_path, monkeypatch):
    from papyrus_content import env

    root = tmp_path / "root"
    (root / "corpora").mkdir(parents=True)
    (root / "corpora" / "papyrus-steering.yml").write_text("custom: true\n")
    monkeypatch.setattr(env, "PAPYRUS_ROOT", root)
    assert env.resolve_corpora_file("corpora/papyrus-steering.yml") == root / "corpora" / "papyrus-steering.yml"
    (root / "corpora" / "papyrus-steering.yml").unlink()
    assert env.resolve_corpora_file("corpora/papyrus-steering.yml") == env.packaged_corpora_file("papyrus-steering.yml")
    assert env.resolve_corpora_file("corpora/not-shipped.yml") == root / "corpora" / "not-shipped.yml"

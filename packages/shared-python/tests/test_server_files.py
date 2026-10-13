from __future__ import annotations

import pytest

from shared_python.server_files import OutsideServerFiles, confine, server_files_root


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    folder = tmp_path / "server-files"
    (folder / "finance").mkdir(parents=True)
    monkeypatch.setenv("SERVER_FILES_ROOT", str(folder))
    return folder


def test_a_relative_path_means_inside_the_folder(root) -> None:
    assert confine("finance") == root.resolve() / "finance"
    assert confine("") == root.resolve()
    assert server_files_root() == root.resolve()


def test_an_absolute_path_inside_is_allowed(root) -> None:
    assert confine(str(root / "finance")) == root.resolve() / "finance"


@pytest.mark.parametrize("path", ["/", "/etc", "..", "finance/../../outside", "~"])
def test_anything_outside_is_refused(path) -> None:
    with pytest.raises(OutsideServerFiles):
        confine(path)


def test_a_symlink_out_of_the_folder_is_refused(root, tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "sneaky").symlink_to(outside)
    with pytest.raises(OutsideServerFiles):
        confine("sneaky")

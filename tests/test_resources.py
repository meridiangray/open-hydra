"""The shared resources (the package's own template/) and the caches over them:
the default schema is the package's, an archive without upstream FTM types is
layered over it file by file, and a cached result is dropped when a file changes."""
import os
import shutil
from pathlib import Path


from hydra import resources, schema  # noqa: E402
from hydra.identity import classify  # noqa: E402
from _template import copy_template  # noqa: E402
from _paths import TEMPLATE as TEMPLATE_DIR  # noqa: E402

TEMPLATE = TEMPLATE_DIR


def test_the_default_resources_are_hydras_own_template():
    assert resources.seed_dir() == TEMPLATE
    schema.load()
    assert Path(schema.LOADED["source"]) == TEMPLATE
    assert schema.resolve("Project")["props"]["organization"]["range"] == "LegalEntity"


def test_an_archive_without_ftm_is_layered_over_the_resources_and_its_patch_applies(tmp_path):
    arch = tmp_path / "thin"
    (arch / ".hydra" / "schema" / "extensions").mkdir(parents=True)
    (arch / ".hydra" / "schema" / "extensions" / "artifact.yaml").write_text(
        "Project:\n  properties:\n    budget:\n      label: Budget\n      type: string\n",
        encoding="utf-8")
    schema.load(root=arch)
    props = schema.resolve("Project")["props"]
    assert "Person" in schema.SCHEMA
    assert "budget" in props
    assert "name" in props and "projectId" in props            # the type itself is still upstream's
    assert "organization" not in props   # the archive's artifact.yaml replaced the resource file at that path
    schema.load()


def test_a_changed_param_file_is_read_again(tmp_path):
    params = tmp_path / "params"
    copy_template(params, ".hydra/schema/params")
    schema.load(root=TEMPLATE)
    before = classify.classify("Person", params)
    assert before["email"].match
    f = params / "Person.param.yaml"
    text = f.read_text(encoding="utf-8").replace("  - email\n", "")
    f.write_text(text, encoding="utf-8")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert not classify.classify("Person", params)["email"].match
    assert classify.classify("Person", params) == classify.classify("Person", params)


def test_activation_names_one_archive_and_is_found_from_below(tmp_path):
    arch = tmp_path / "arch"
    copy_template(arch)
    work = tmp_path / "work" / "deep"
    work.mkdir(parents=True)
    resources.activate(arch, start=tmp_path / "work")
    assert resources.activated(start=work) == arch.resolve()
    resources.deactivate(start=work)
    assert resources.activated(start=work) is None


def test_activating_a_folder_that_is_not_an_archive_is_refused(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        resources.activate(tmp_path)

"""Flag package extraction must not confuse country codes with language flags."""
import io
import tarfile

import pytest

from hydra.wiki import flagdata, flags


def package(files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, body in files:
            entry = tarfile.TarInfo(name)
            entry.size = len(body)
            archive.addfile(entry, io.BytesIO(body))
    return out.getvalue()


@pytest.mark.parametrize("nested_last", [False, True])
def test_country_flags_are_not_overwritten_by_nested_language_flags(tmp_path, monkeypatch, nested_last):
    canada = b'<svg id="canada"/>'
    catalan = b'<svg id="catalan"/>'
    circle = [
        ("package/flags/ca.svg", canada),
        ("package/flags/es-ct.svg", catalan),
        ("package/flags/language/ca.svg", catalan),
        ("package/flags/language/zz.svg", catalan),
    ]
    if not nested_last:
        circle.reverse()
    rect = [
        ("package/flags/4x3/ca.svg", canada),
        ("package/flags/4x3/language/ca.svg", catalan),
        ("package/flags/1x1/ca.svg", canada),
    ]
    packages = {"circle-flags": package(circle), "flag-icons": package(rect)}
    monkeypatch.setattr(flagdata.urllib.request, "urlopen",
                        lambda url, timeout: io.BytesIO(packages[next(k for k in packages if k in url)]))

    dest = flagdata.fetch(tmp_path / "flags")
    assert (dest / "circle/ca.svg").read_bytes() == canada
    assert (dest / "circle/es-ct.svg").read_bytes() == catalan
    assert not (dest / "circle/zz.svg").exists()
    assert (dest / "rect/ca.svg").read_bytes() == canada
    assert (dest / "square/ca.svg").read_bytes() == canada

    monkeypatch.delenv("HYDRA_FLAGS_DIR", raising=False)
    monkeypatch.setattr(flagdata, "DIR", dest)
    monkeypatch.setattr(flags, "DEFAULT", "circle")
    monkeypatch.setattr(flags, "ENABLED", True)
    assert flags.code("Canada") == "ca"
    assert flags.file_for("circle", "ca").read_bytes() == canada
    assert "src='/flag/circle/ca.svg'" in flags.img("Canada")

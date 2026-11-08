"""The wiki: display methods on a small dynasty, red links, and the server's addresses."""
import json
import re
import threading
import urllib.error
import urllib.request

from hydra.cli import init as hinit
from hydra.universe import build, layer
from hydra.wiki import site, views

P = lambda i, s, **p: {"id": i, "schema": s, "properties": {k: v if isinstance(v, list) else [v] for k, v in p.items()}}


def dynasty(tmp_path):
    root = hinit.create(tmp_path / "dyn", name="dyn", prefix="dyn")
    recs = [
        P("k", "Person", name="Old King", gender="male", nationality="sa", birthDate="1900", deathDate="1960",
          notes="House: Testa\nSource: https://en.wikipedia.org/wiki/Old_King"),
        P("q", "Person", name="The Queen", gender="female"),
        P("a", "Person", name="Amir One", gender="male", birthDate="1925", deathDate="1990"),
        P("b", "Person", name="Amira Two", gender="female", birthDate="1930"),
        P("m", "PublicBody", name="Ministry of Tests", country="sa"),
        P("pos", "Position", name="Minister of Tests", organization="Ministry of Tests"),
        P("o1", "Occupancy", holder="Old King", post="Minister of Tests", startDate="1940", endDate="1950",
          notes="Recorded as: Minister of Tests 1940–50"),
        P("o2", "Occupancy", holder="Amir One", post="Minister of Tests", startDate="1950", endDate="1951"),
        P("f1", "Family", person="Amir One", relative="Old King", relationship="father"),
        P("f2", "Family", person="Amira Two", relative="Old King", relationship="father"),
        P("f3", "Family", person="Amir One", relative="The Queen", relationship="mother",
          publisherUrl="https://en.wikipedia.org/wiki/Amir_One"),
        P("f4", "Family", person="Amira Two", relative="Nobody Recorded", relationship="mother"),
    ]
    (root / "collections" / "dyn.json").write_text(json.dumps(recs), encoding="utf-8")
    build.build(root)
    return root


def text(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))


def test_heading_fonts_follow_sidebar_font_by_default():
    for theme in site.THEMES:
        sheet = site.css(theme)
        assert "--serif:var(--sans);" in sheet
        assert f"--sans:{site._SANS};" in sheet
    custom = site.theme_vars(custom={"fonts": {"heading": "Example Heading", "body": "Example Body"}})
    assert "--serif:Example Heading;" in custom
    assert "--sans:Example Body;" in custom


def test_browse_categories_show_labels_before_counts(tmp_path):
    from hydra.wiki import landing

    w = site.Wiki(dynasty(tmp_path))
    L = site.Links(static=False)
    html = landing.domains(w, L)
    assert "<nav class='wide domains'" in html
    assert "aria-label='Entry categories'" in html
    assert "<span class=lbl>People</span><span class=count>4</span>" in html
    assert html.count("class=card") == len({w.pages[b]["schema"] for b in w.listed})
    assert L.cat("type", "Person") in html
    assert "<b>" not in html


def test_landing_section_labels(tmp_path, monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    from hydra.wiki import landing

    root = dynasty(tmp_path)
    (root / "collections" / "current.json").write_text(json.dumps([
        P("o3", "Occupancy", holder="The Queen", post="Minister of Tests", startDate="1960")
    ]), encoding="utf-8")
    build.build(root)
    w, L = site.Wiki(root), site.Links(static=False)
    monkeypatch.setattr(landing, "date", SimpleNamespace(today=lambda: date(1965, 1, 1)))
    assert "<h2>Featured entry</h2>" in landing.featured(w, L)
    assert "<h2>Officeholders " in landing.in_office(w, L)
    assert "<h2>Anniversaries</h2>" in landing.years_ago(w, L)
    assert "<h2>Timeline</h2>" in landing.decades(w, L)
    assert "<h2>Data quality</h2>" in landing.attention(w, L)
    assert "<h1>Officeholders</h1>" in w.render_current(L)
    monkeypatch.setattr(landing, "changes", lambda *args: [{"collections": [{"added": ["dyn:k"]}]}])
    assert "<h2>New entries</h2>" in landing.added(w, L)


def test_utility_pages_have_clear_tables_and_empty_states(tmp_path, monkeypatch):
    from hydra.wiki import landing

    w, L = site.Wiki(dynasty(tmp_path)), site.Links(static=False)
    assert "Entry types</th><th>Source coverage" in w.render_collections(L)
    monkeypatch.setattr(landing, "changes", lambda *args: [])
    assert "No archive changes recorded yet." in w.render_changes(L)
    w.provenance["origins"] = []
    sources = w.render_sources(L)
    assert "Source coverage</th>" in sources
    assert "id=source-browser" in sources
    assert "Coverage by collection" in sources
    assert "data-source-filter='missing'" in sources
    body = next(iter(w.pages))
    assert "<table class=wikitable>" in w.render_talk(L, body)


def test_source_browser_deduplicates_records_and_links_saved_documents(tmp_path):
    w = site.Wiki(dynasty(tmp_path))
    bodies = {p["title"]: b for b, p in w.pages.items()}
    url = "https://publisher.example/evidence"
    w.pages["evidence"] = {
        "body": "evidence", "title": "Saved evidence", "schema": "Article",
        "infobox": [{"prop": k, "values": [{"value": v}]} for k, v in
                    (("sourceUrl", url), ("publisherUrl", "https://publisher.example/"),
                     ("publisher", "Example publisher"), ("retrievedAt", "2025-01-01"))],
    }
    citation = {"member": "self", "record": "one-record", "urls": [url, "https://publisher.example/"],
                "docs": [{"h": "evidence", "title": "Saved evidence"}], "quote": "An editorial note."}
    for title in ("Old King", "The Queen"):
        w.pages[bodies[title]]["citations"].append(dict(citation))
    data = w.source_catalog
    saved = next(d for d in data["documents"] if d["id"] == "document:evidence")
    assert saved["kind"] == "saved" and saved["group"] == "publisher.example"
    assert saved["retrieved"] == "2025-01-01"
    assert len(saved["records"]) == 1 and len(saved["entries"]) == 2
    assert saved["notes"] == ["An editorial note."]
    assert not any(d["id"] == "url:" + url for d in data["documents"])
    homepage = next(d for d in data["documents"] if d["id"] == "url:https://publisher.example/")
    assert homepage["kind"] == "link"
    assert set(saved["records"][0]["entries"]) == {bodies["Old King"], bodies["The Queen"]}
    family = next(d for d in data["documents"] if d["url"].endswith("/Amir_One"))
    assert len(family["records"]) == 1 and len(family["entries"]) >= 2
    assert any(entry["missing"] for entry in data["entries"])
    assert any(entry["coverage"] == "wiki" for entry in data["entries"])


def test_source_browser_escapes_evidence_and_supports_static_links(tmp_path):
    from hydra.wiki import sourcebrowser

    w = site.Wiki(dynasty(tmp_path))
    page = next(p for p in w.pages.values() if p["citations"])
    payload = "</script><img src=x onerror=alert(1)>"
    page["citations"][0]["quote"] = payload
    page["citations"][0]["urls"] = ["https://example.test/source", "javascript:alert(1)"]
    for static in (False, True):
        links = site.Links(static=static)
        rendered = sourcebrowser.render(w, links)
        assert payload not in rendered
        encoded = re.search(r"id=source-data>(.*?)</script>", rendered, re.S).group(1)
        data = json.loads(encoded)
        assert any(payload in doc["notes"] for doc in data["documents"])
        assert all(not doc["url"].startswith("javascript:") for doc in data["documents"])
        assert all(entry["href"] == links.page(entry["id"]) for entry in data["entries"])
    assert sourcebrowser.safe_url("file:///private/file") == ""
    assert sourcebrowser.safe_url("https://[broken") == ""


def test_source_browser_empty_archive(tmp_path):
    root = hinit.create(tmp_path / "empty", name="empty", prefix="empty")
    build.build(root)
    w = site.Wiki(root)
    assert w.source_catalog == {"documents": [], "entries": []}
    rendered = w.render_sources(site.Links(static=False))
    assert "id=source-browser" in rendered and "Coverage by collection" in rendered


def test_display_methods(tmp_path):
    root = dynasty(tmp_path)
    w = site.Wiki(root)
    L = site.Links(static=False)
    body = {p["title"]: b for b, p in w.pages.items()}
    king = text(w.render_page(L, body["Old King"]))
    assert "served as Minister of Tests (1940–1950)" in king
    assert "Died 1960 [1] (aged 59–60)" in king
    assert "House Testa" in king and "Old King – Wikipedia" in king
    assert "Succeeded by" in king and "Amir One" in king.split("Succeeded by")[1]
    assert "Issue (2)" in king and "Amira Two" in king
    assert "Amir One – Wikipedia" not in king            # a child's link belongs on the child's page
    amir = text(w.render_page(L, body["Amir One"]))
    assert "son of Old King [" in amir and "Old King" in amir.split("Preceded by")[1]
    assert "Paternal half-siblings (1)" in amir and "Amir One – Wikipedia" in amir
    post = text(w.render_page(L, body["Minister of Tests"]))
    assert "2 people have held it since 1940" in post and "10 years" in post and "1 year " in post
    cats = w.page_cats[body["Old King"]]
    assert ("births", "1900") in cats and ("office", "Minister of Tests") in cats
    assert views.country("SA") == "Saudi Arabia"


def test_a_name_with_no_record_is_a_red_link(tmp_path):
    root = dynasty(tmp_path)
    w = site.Wiki(root)
    body = {p["title"]: b for b, p in w.pages.items()}
    html = w.render_page(site.Links(static=False), body["Amira Two"])
    assert "class=new" in html and "Nobody Recorded" in html
    assert not any(p["title"] == "Nobody Recorded" for p in w.pages.values())   # a stub gets no page


def test_server_addresses(tmp_path):
    root = dynasty(tmp_path)
    httpd, w = site.serve(root, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect)

    def get(path):
        try:
            r = opener.open(f"http://127.0.0.1:{port}{path}")
            return r.status, r.headers.get("Location")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location")
    try:
        b = next(b for b, p in w.pages.items() if p["title"] == "Old King")
        h = w.pages[b]["h"]
        assert get(f"/e/{b}") == (200, None)
        assert get(f"/e/{h}")[0] == 301 and get(f"/e/{h}")[1] == f"/e/{b}"
        assert get("/search?q=old+king") == (302, f"/e/{b}")
        assert get("/e/zzzzzzzzzzzz")[0] == 404 and get("/")[0] == 200
        assert get("/c/births/1900")[0] == 200
    finally:
        httpd.shutdown()


def test_rule_snapshots_are_loaded_once_per_wiki(tmp_path, monkeypatch):
    from hydra import keys, kinship, vocab

    root = dynasty(tmp_path)
    calls = {"kin": 0, "keys": 0, "vocab": 0}
    for name, module in (("kin", kinship), ("keys", keys), ("vocab", vocab)):
        original = module.load

        def load(root=None, _name=name, _load=original):
            calls[_name] += 1
            return _load(root)

        monkeypatch.setattr(module, "load", load)
    w = site.Wiki(root)
    assert calls == {"kin": 1, "keys": 1, "vocab": 1}
    snapshots = w.kin, w.keyconf, w.vocab
    for _ in range(3):
        assert w.kin is snapshots[0]
        assert w.keyconf is snapshots[1]
        assert w.vocab is snapshots[2]
    assert calls == {"kin": 1, "keys": 1, "vocab": 1}
    assert not w.kin.is_("guardian", "parent")
    (root / ".hydra/rules/kinship.yaml").write_text("words: {guardian: {is: parent}}\n", encoding="utf-8")
    other = site.Wiki(root)
    assert other.kin.is_("guardian", "parent")
    assert not w.kin.is_("guardian", "parent")
    assert other.kin is not w.kin
    assert other.keyconf is not w.keyconf
    assert other.vocab is not w.vocab


def test_schema_is_prepared_before_serving(tmp_path, monkeypatch):
    from hydra import schema

    root = dynasty(tmp_path)
    schema.SCHEMA.clear()
    server, w = site.serve(root, 0)
    try:
        assert schema.LOADED["source"] == str(root)
        assert schema.SCHEMA
        monkeypatch.setattr(schema, "load", lambda *args: (_ for _ in ()).throw(AssertionError("late schema load")))
        w.render_page(site.Links(static=False), next(iter(w.pages)))
    finally:
        server.server_close()


def test_server_entry_cache_is_bounded_and_snapshot_local(tmp_path, monkeypatch):
    root = dynasty(tmp_path)
    calls = []
    original = site.Wiki.render_page

    def render(self, links, body):
        calls.append((id(self), body))
        return original(self, links, body)

    monkeypatch.setattr(site.Wiki, "render_page", render)
    for _ in range(2):
        server, w = site.serve(root, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        body = next(iter(w.pages))
        url = f"http://127.0.0.1:{server.server_address[1]}/e/{body}"
        try:
            with urllib.request.urlopen(url) as response:
                first = response.read()
            with urllib.request.urlopen(url + "?mode=dark") as response:
                assert response.read() == first
            assert calls.count((id(w), body)) == 1
            assert w.page_cache.cache_info().maxsize == 128
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
    assert len(calls) == 2


def test_collection_wiki_overrides_resolve_per_page(tmp_path):
    """`hydra.yaml` `collections.X.wiki:` gives one collection's pages its own roles/sections/icons/badge_rules."""
    root = hinit.create(tmp_path / "a", name="a", prefix="a")
    (root / "collections" / "people.json").write_text(json.dumps([
        P("a1", "Person", name="Base Ann", position="mayor of X"),
    ]), encoding="utf-8")
    (root / "collections" / "cits.json").write_text(json.dumps([
        P("c1", "Citizen", name="Cit Carol", position="mayor of Y"),
    ]), encoding="utf-8")
    with open(root / "hydra.yaml", "a", encoding="utf-8") as f:
        f.write("collections:\n  cits:\n    wiki:\n      roles: {person: Citizen}\n"
                "      sections: {Citizen: [family, offices]}\n"
                "      badge_rules: {mayor: {label: Mayor, group: role, icon: crown, title: mayor}}\n"
                "      icons: {Citizen: crown}\n")
    build.build(root)
    w = site.Wiki(root)
    by_t = {p["title"]: p for p in w.pages.values()}
    carol, ann = by_t["Cit Carol"], by_t["Base Ann"]
    assert carol["collection"] == ["cits"] and ann["collection"] == ["people"]
    assert [m.__name__ for m in views.methods_for("Citizen", w.conf_for(carol))] == ["family", "offices"]
    assert w.reg_for(carol).roles.PERSON == "Citizen" and w.reg_for(carol).icons.token("Citizen") == "crown"
    assert "mayor" in views.Ctx(w, None, carol).reg.badges.rules
    assert w.reg_for(ann).roles.PERSON == "Person" and "mayor" not in views.Ctx(w, None, ann).reg.badges.rules

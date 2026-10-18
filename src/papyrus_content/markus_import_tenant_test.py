from papyrus_content.markus_import import DirMediaStore, ImportOptions, plan_import, run_import
from papyrus_content.markus_import_commands import import_options_from_flags
from procedures.newsroom.tests.test_tenancy import InMemoryGraphQLBackend, tenant_client

PIXEL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082"
)


class ImportBackend(InMemoryGraphQLBackend):
    def _read(self, field, variables):
        if field == "listItems":
            return {"items": [dict(row) for row in self.tables.get("Item", {}).values()], "nextToken": None}
        return super()._read(field, variables)


def content_directory(tmp_path, name, hello_title):
    content = tmp_path / name
    (content / "articles").mkdir(parents=True)
    (content / "assets").mkdir()
    (content / "assets" / "cover.png").write_bytes(PIXEL_PNG)
    (content / "articles" / "hello.md").write_text(
        f"---\ntitle: {hello_title} Hello\ncover: assets/cover.png\n---\nBody of the hello article.\n", encoding="utf-8"
    )
    (content / "articles" / "second.md").write_text(f"---\ntitle: {hello_title} Second\n---\nSecond body.\n", encoding="utf-8")
    return content


def import_for(tenant_id, content, client, bucket):
    options = ImportOptions(content_dir=content, draft_dirs={"drafts": "articles"}, tenant_id=tenant_id)
    store = DirMediaStore(bucket)
    return run_import(plan_import(options, client, store), client, store, apply=True)


def test_the_tenant_flag_becomes_an_import_option_and_is_validated(monkeypatch):
    monkeypatch.delenv("PAPYRUS_TENANT_ID", raising=False)
    base = {"content-dir": "content"}
    assert import_options_from_flags({**base, "tenant": "alpha"}).tenant_id == "alpha"
    assert import_options_from_flags(base).tenant_id is None
    monkeypatch.setenv("PAPYRUS_TENANT_ID", "gamma")
    assert import_options_from_flags(base).tenant_id == "gamma"
    try:
        import_options_from_flags({**base, "tenant": "Bad Tenant"})
    except ValueError:
        return
    raise AssertionError("an invalid tenant id must be refused")


def test_importing_without_a_tenant_keeps_the_existing_item_ids(tmp_path):
    backend = ImportBackend()
    report = import_for(None, content_directory(tmp_path, "plain", "Plain"), tenant_client(backend, None), tmp_path / "bucket")
    assert report.ok
    assert "item-articles-hello" in backend.tables["Item"]
    assert all("tenantId" not in row for row in backend.tables["Item"].values())


def test_tenant_a_importing_leaves_tenant_b_same_slug_article_unchanged(tmp_path):
    backend = ImportBackend()
    beta_report = import_for("beta", content_directory(tmp_path, "beta", "Beta"), tenant_client(backend, "beta"), tmp_path / "bucket")
    beta_before = {key: dict(row) for key, row in backend.tables["Item"].items()}
    alpha_report = import_for("alpha", content_directory(tmp_path, "alpha", "Alpha"), tenant_client(backend, "alpha"), tmp_path / "bucket")
    assert beta_report.ok and alpha_report.ok
    for key, row in beta_before.items():
        assert backend.tables["Item"][key] == row
    alpha_items = {key: row for key, row in backend.tables["Item"].items() if row["tenantId"] == "alpha"}
    assert len(alpha_items) == len(beta_before)
    assert {row["slug"] for row in alpha_items.values()} == {row["slug"] for row in beta_before.values()}
    assert alpha_items.keys().isdisjoint(beta_before.keys())


def test_each_tenant_media_lands_under_its_own_storage_prefix(tmp_path):
    backend = ImportBackend()
    import_for("alpha", content_directory(tmp_path, "alpha", "Alpha"), tenant_client(backend, "alpha"), tmp_path / "bucket")
    import_for("beta", content_directory(tmp_path, "beta", "Beta"), tenant_client(backend, "beta"), tmp_path / "bucket")
    paths = {row["tenantId"]: row["storagePath"] for row in backend.tables["MediaAsset"].values()}
    assert paths["alpha"].startswith("media/alpha/") and paths["beta"].startswith("media/beta/")
    stored = {path.relative_to(tmp_path / "bucket").parts[:2] for path in (tmp_path / "bucket").rglob("*") if path.is_file()}
    assert ("media", "alpha") in stored and ("media", "beta") in stored


def test_importing_the_same_content_again_for_a_tenant_changes_nothing(tmp_path):
    backend = ImportBackend()
    client = tenant_client(backend, "alpha")
    content = content_directory(tmp_path, "alpha", "Alpha")
    import_for("alpha", content, client, tmp_path / "bucket")
    second = import_for("alpha", content, client, tmp_path / "bucket")
    assert second.created == 0 and second.updated == 0 and second.unchanged > 0

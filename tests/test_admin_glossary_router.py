from __future__ import annotations

from app.models import GlossaryCache


def test_admin_get_patch_delete_restore_glossary_cache(client, db_session):
    cache = GlossaryCache(language="fr", terms={"TAM": "marche total adressable"})
    db_session.add(cache)
    db_session.commit()

    get_resp = client.get("/api/admin/glossary/fr")
    assert get_resp.status_code == 200
    assert get_resp.json()["deleted_at"] is None

    patch_resp = client.patch(
        "/api/admin/glossary/fr", json={"terms": {"TAM": "marche total adressable corrige"}}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["terms"]["TAM"] == "marche total adressable corrige"

    delete_resp = client.delete("/api/admin/glossary/fr")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted_at"] is not None

    active_only = client.get("/api/admin/glossary").json()
    assert "fr" not in [g["language"] for g in active_only["items"]]

    incl_deleted = client.get("/api/admin/glossary", params={"include_deleted": True}).json()
    assert "fr" in [g["language"] for g in incl_deleted["items"]]

    restore_resp = client.post("/api/admin/glossary/fr/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None


async def test_soft_deleted_glossary_cache_is_retranslated_in_place(
    db_session, monkeypatch
):
    """The PK is the language itself, so a soft-deleted row can't just be
    superseded by a fresh insert on next use — it must be updated in place
    and un-deleted, without ever raising a PK-collision error."""
    import app.services.glossary as glossary_module

    cache = GlossaryCache(language="es", terms={"TAM": "stale definition"})
    db_session.add(cache)
    db_session.commit()

    glossary_module.soft_delete_glossary_cache(db_session, cache)
    assert cache.deleted_at is not None

    async def fake_translate(target_language: str) -> dict[str, str]:
        return {"TAM": "definicion fresca"}

    monkeypatch.setattr(glossary_module, "_translate_glossary", fake_translate)

    terms = await glossary_module.get_or_create_glossary(db_session, "es")
    assert terms["TAM"] == "definicion fresca"

    refreshed = db_session.get(GlossaryCache, "es")
    assert refreshed.deleted_at is None
    assert refreshed.terms["TAM"] == "definicion fresca"

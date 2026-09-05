"""Public Android App Links contract for the staging Google callback."""

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings


def test_staging_assetlinks_is_public_and_contains_only_android_contract(monkeypatch) -> None:
    settings = Settings(
        app_env="staging",
        database_url="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        google_android_app_link_package="com.kairo.app.staging",
        google_android_app_link_cert_sha256="75:55:FD:AB:41:38:41:B3:A9:DF:B9:65:C4:FE:E4:D8:09:BB:53:50:35:23:EC:EB:D9:FB:84:60:DE:2A:F8:8A",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    with TestClient(main.create_app()) as client:
        response = client.get("/.well-known/assetlinks.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    target = response.json()[0]["target"]
    assert response.json()[0]["relation"] == ["delegate_permission/common.handle_all_urls"]
    assert target["namespace"] == "android_app"
    assert target["package_name"] == "com.kairo.app.staging"
    assert target["package_name"] != "com.kairo.app"
    assert target["sha256_cert_fingerprints"] == [settings.google_android_app_link_cert_sha256]

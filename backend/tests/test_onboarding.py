from __future__ import annotations


def _register(client) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": "pw12345", "name": "A"},
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


def test_connect_mint_and_handoff_redeem(client):
    token = _register(client)
    auth = {"Authorization": f"Bearer {token}"}

    mint = client.post("/api/onboard/connect", headers=auth)
    assert mint.status_code == 200
    body = mint.json()
    assert body["connectUri"].startswith("shadow://connect?mcp=")
    assert "handoff=" in body["connectUri"]
    code = body["handoff"]

    redeem = client.post(f"/.well-known/shadownet/onboard/handoff/{code}")
    assert redeem.status_code == 200
    tokens = redeem.json()
    assert tokens["accessToken"]
    assert tokens["refreshToken"]

    from app.onboarding import validate_access_token

    assert validate_access_token(tokens["accessToken"]) is not None

    # Single-use: second redemption fails.
    again = client.post(f"/.well-known/shadownet/onboard/handoff/{code}")
    assert again.status_code == 404


def test_refresh_rotation_and_reuse_detection(client):
    token = _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    code = client.post("/api/onboard/connect", headers=auth).json()["handoff"]
    tokens = client.post(f"/.well-known/shadownet/onboard/handoff/{code}").json()
    old_refresh = tokens["refreshToken"]

    r1 = client.post(
        "/.well-known/shadownet/onboard/refresh",
        headers={"Authorization": f"Bearer {old_refresh}"},
    )
    assert r1.status_code == 200
    new_refresh = r1.json()["refreshToken"]
    assert new_refresh != old_refresh

    # Reusing the rotated (old) refresh token revokes the family.
    reuse = client.post(
        "/.well-known/shadownet/onboard/refresh",
        headers={"Authorization": f"Bearer {old_refresh}"},
    )
    assert reuse.status_code == 401

    from app.onboarding import validate_access_token

    assert validate_access_token(r1.json()["accessToken"]) is None


def test_handoff_malformed_code(client):
    resp = client.post("/.well-known/shadownet/onboard/handoff/short")
    assert resp.status_code == 404
    assert resp.json()["error"] == "handoff_unknown"


def test_inline_form(client):
    token = _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    mint = client.post("/api/onboard/connect?form=inline", headers=auth)
    assert mint.status_code == 200
    uri = mint.json()["connectUri"]
    assert "token=" in uri and "handoff=" not in uri

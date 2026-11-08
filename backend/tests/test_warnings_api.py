"""Public warnings (docs/notes/w5-i18n.md): roles, validation, the publish gate, withdrawal, and the public read."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.routes import warnings as warnings_routes
from tests.conftest import Env

PUBLIC_FIELDS = {"id", "title", "body", "lang", "country_code", "hazard_type", "published_at"}


def _mount_if_needed(env: Env) -> None:
    """main.py includes the warnings router in the owner's integration step. Until then, mount it here so this
    file runs on its own. Routes are inserted ahead of the /api catch-all."""
    if any(getattr(r, "path", None) == "/api/warnings" for r in env.app.router.routes):
        return
    holder = APIRouter(prefix="/api")
    holder.include_router(warnings_routes.router)
    for route in reversed(holder.routes):
        env.app.router.routes.insert(0, route)


def _draft(env: Env, username: str = "analyst", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Flood warning: Jakarta south",
        "body": "Water levels are rising. Move to higher ground and follow official instructions.",
        "lang": "en",
        "hazard_type": "FLOOD",
        "country_code": "id",
    }
    body.update(overrides)
    response = env.api("POST", "/api/warnings", env.token(username), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _publish(env: Env, warning: dict[str, Any], username: str = "approver") -> Any:
    return env.api("POST", f"/api/warnings/{warning['id']}/publish", env.token(username),
                   json={"content_sha256": warning["content_sha256"]})


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def _no_usernames(payload: Any) -> None:
    text = repr(payload)
    for name in ("analyst", "approver", "reviewer", "viewer", "admin"):
        assert name not in text, f"username {name!r} leaked in a response"


def _env(make_env: Any) -> Env:
    env = make_env()
    _mount_if_needed(env)
    for username in ("admin", "analyst", "reviewer", "approver", "viewer"):
        env.login(username)
    return env


# ----- create and list ---------------------------------------------------------------------------

def test_analyst_creates_draft_and_viewer_lists_it(make_env: Any) -> None:
    env = _env(make_env)
    warning = _draft(env)
    assert warning["status"] == "DRAFT"
    assert warning["country_code"] == "ID"
    assert warning["decided_by"] is None and warning["published_at"] is None
    assert len(warning["content_sha256"]) == 64

    listed = env.api("GET", "/api/warnings", env.token("viewer"))
    assert listed.status_code == 200
    assert [w["id"] for w in listed.json()] == [warning["id"]]
    _no_usernames(listed.json())
    _no_usernames(warning)


def test_viewer_and_anonymous_cannot_create(make_env: Any) -> None:
    env = _env(make_env)
    body = {"title": "t", "body": "b", "lang": "en", "hazard_type": "FLOOD"}
    viewer = env.api("POST", "/api/warnings", env.token("viewer"), json=body)
    assert viewer.status_code == 403
    assert _error_code(viewer) == "FORBIDDEN"
    anonymous = env.api("POST", "/api/warnings", None, json=body)
    assert anonymous.status_code == 401


def test_list_filters_by_status_and_country_newest_first(make_env: Any) -> None:
    env = _env(make_env)
    first = _draft(env, title="First", country_code="ID")
    second = _draft(env, title="Second", country_code="JP")
    assert _publish(env, second).status_code == 200

    drafts = env.api("GET", "/api/warnings?status=DRAFT", env.token("viewer")).json()
    assert [w["id"] for w in drafts] == [first["id"]]
    jp = env.api("GET", "/api/warnings?country=jp", env.token("viewer")).json()
    assert [w["id"] for w in jp] == [second["id"]]
    everything = env.api("GET", "/api/warnings", env.token("viewer")).json()
    assert {w["id"] for w in everything} == {first["id"], second["id"]}
    bad_status = env.api("GET", "/api/warnings?status=GONE", env.token("viewer"))
    assert bad_status.status_code == 422


# ----- validation ---------------------------------------------------------------------------------

def test_html_characters_are_refused(make_env: Any) -> None:
    env = _env(make_env)
    base = {"title": "Flood", "body": "Stay safe.", "lang": "en", "hazard_type": "FLOOD"}
    cases = [
        {**base, "title": "<b>Flood</b>"},
        {**base, "body": "Stay <script>alert(1)</script>"},
        {**base, "body": "a > b"},
    ]
    for body in cases:
        response = env.api("POST", "/api/warnings", env.token("analyst"), json=body)
        assert response.status_code == 422, body
        assert _error_code(response) == "VALIDATION_FAILED"


def test_bad_lang_country_hazard_and_extra_fields_are_refused(make_env: Any) -> None:
    env = _env(make_env)
    base = {"title": "Flood", "body": "Stay safe.", "lang": "en", "hazard_type": "FLOOD"}
    cases = [
        {**base, "lang": "fr"},
        {**base, "country_code": "XX"},
        {**base, "country_code": "IDN"},
        {**base, "hazard_type": "VOLCANO"},
        {**base, "status": "PUBLISHED"},
        {**base, "title": ""},
        {**base, "title": "x" * 121},
        {**base, "body": "x" * 2001},
    ]
    for body in cases:
        response = env.api("POST", "/api/warnings", env.token("analyst"), json=body)
        assert response.status_code == 422, body


def test_body_allows_newlines_but_not_control_characters(make_env: Any) -> None:
    env = _env(make_env)
    ok = _draft(env, body="Line one.\nLine two.")
    assert "\n" in ok["body"]
    bad = env.api("POST", "/api/warnings", env.token("analyst"),
                  json={"title": "Flood", "body": "bell\x07", "lang": "en", "hazard_type": "FLOOD"})
    assert bad.status_code == 422


# ----- publish gate ------------------------------------------------------------------------------

def test_publish_by_approver_sets_decider_and_audits(make_env: Any) -> None:
    env = _env(make_env)
    warning = _draft(env, "analyst")
    response = _publish(env, warning, "approver")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "PUBLISHED"
    assert body["decided_by"] is not None
    assert body["published_at"] is not None
    _no_usernames(body)
    actions = [row["action"] for row in env.audit_rows()]
    assert "warning.drafted" in actions and "warning.published" in actions


def test_creator_cannot_publish_own_draft(make_env: Any) -> None:
    env = _env(make_env)
    warning = _draft(env, "approver")
    response = _publish(env, warning, "approver")
    assert response.status_code == 403
    assert _error_code(response) == "SELF_APPROVAL_NOT_ALLOWED"


def test_analyst_and_reviewer_cannot_publish(make_env: Any) -> None:
    env = _env(make_env)
    warning = _draft(env, "analyst")
    assert _publish(env, warning, "analyst").status_code == 403
    assert _publish(env, warning, "reviewer").status_code == 403
    assert _publish(env, warning, "viewer").status_code == 403


def test_hash_mismatch_is_409_content_changed(make_env: Any) -> None:
    env = _env(make_env)
    warning = _draft(env, "analyst")
    response = env.api("POST", f"/api/warnings/{warning['id']}/publish", env.token("approver"),
                       json={"content_sha256": "0" * 64})
    assert response.status_code == 409
    assert _error_code(response) == "CONTENT_CHANGED"
    listed = env.api("GET", "/api/warnings?status=DRAFT", env.token("viewer")).json()
    assert [w["id"] for w in listed] == [warning["id"]]


def test_republish_is_409(make_env: Any) -> None:
    env = _env(make_env)
    warning = _draft(env, "analyst")
    assert _publish(env, warning, "approver").status_code == 200
    again = _publish(env, warning, "admin")
    assert again.status_code == 409
    assert _error_code(again) == "INVALID_STATE"


def test_identical_content_cannot_be_published_twice(make_env: Any) -> None:
    env = _env(make_env)
    first = _draft(env, "analyst")
    second = _draft(env, "analyst")
    assert _publish(env, first, "approver").status_code == 200
    response = _publish(env, second, "approver")
    assert response.status_code == 409
    assert _error_code(response) == "CONFLICT"


def test_malformed_publish_body_is_refused(make_env: Any) -> None:
    env = _env(make_env)
    warning = _draft(env, "analyst")
    response = env.api("POST", f"/api/warnings/{warning['id']}/publish", env.token("approver"),
                       json={"content_sha256": warning["content_sha256"], "decided_by": "x"})
    assert response.status_code == 422


# ----- withdraw ----------------------------------------------------------------------------------

def test_withdraw_published_warning(make_env: Any) -> None:
    env = _env(make_env)
    warning = _draft(env, "analyst")
    _publish(env, warning, "approver")
    response = env.api("POST", f"/api/warnings/{warning['id']}/withdraw", env.token("approver"))
    assert response.status_code == 200
    assert response.json()["status"] == "WITHDRAWN"
    assert response.json()["withdrawn_at"] is not None
    assert "warning.withdrawn" in [row["action"] for row in env.audit_rows()]


def test_withdraw_needs_published_and_approver_role(make_env: Any) -> None:
    env = _env(make_env)
    warning = _draft(env, "analyst")
    draft_withdraw = env.api("POST", f"/api/warnings/{warning['id']}/withdraw", env.token("approver"))
    assert draft_withdraw.status_code == 409
    _publish(env, warning, "approver")
    viewer = env.api("POST", f"/api/warnings/{warning['id']}/withdraw", env.token("viewer"))
    assert viewer.status_code == 403
    analyst = env.api("POST", f"/api/warnings/{warning['id']}/withdraw", env.token("analyst"))
    assert analyst.status_code == 403


# ----- public read -------------------------------------------------------------------------------

def test_public_route_needs_no_auth_and_returns_only_published(make_env: Any) -> None:
    env = _env(make_env)
    published = _draft(env, "analyst", title="Published one", lang="en")
    _publish(env, published, "approver")
    _draft(env, "analyst", title="Still a draft")
    withdrawn = _draft(env, "analyst", title="Withdrawn one", lang="id", body="Tetap waspada terhadap banjir.")
    _publish(env, withdrawn, "approver")
    env.api("POST", f"/api/warnings/{withdrawn['id']}/withdraw", env.token("approver"))

    response = env.api("GET", "/api/public/warnings", None)  # no session, no API key
    assert response.status_code == 200
    items = response.json()
    assert [item["id"] for item in items] == [published["id"]]
    assert set(items[0].keys()) == PUBLIC_FIELDS
    _no_usernames(items)
    assert response.headers["cache-control"] == "public, max-age=60"


def test_public_route_filters_by_lang_and_country(make_env: Any) -> None:
    env = _env(make_env)
    en = _draft(env, "analyst", title="English", lang="en", country_code="ID")
    id_ = _draft(env, "analyst", title="Bahasa", lang="id", country_code="ID",
                 body="Peringatan banjir di wilayah ini.")
    jp = _draft(env, "analyst", title="Japan", lang="en", country_code="JP")
    for w in (en, id_, jp):
        _publish(env, w, "approver")

    by_lang = env.api("GET", "/api/public/warnings?lang=id", None).json()
    assert [w["id"] for w in by_lang] == [id_["id"]]
    by_country = env.api("GET", "/api/public/warnings?country=JP", None).json()
    assert [w["id"] for w in by_country] == [jp["id"]]
    assert env.api("GET", "/api/public/warnings?lang=fr", None).status_code == 422
    assert env.api("GET", "/api/public/warnings?country=XX", None).status_code == 422


def test_public_route_ignores_session_cookie_for_visibility(make_env: Any) -> None:
    env = _env(make_env)
    draft = _draft(env, "analyst")
    response = env.api("GET", "/api/public/warnings", env.token("admin"))
    assert all(item["id"] != draft["id"] for item in response.json())

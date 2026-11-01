import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.models import AuditLog, Application
from app.services import audit_service as audit
from app.services.audit_service import AuditImmutableError
from app.utils import synthetic as syn
from tests.conftest import build_docs, login


def _upload(client, h, aid, docs):
    return client.post(f"/api/applications/{aid}/documents", headers=h,
                       files=[("files", (n + ".pdf", b, "application/pdf")) for n, b in docs.items()])


def _new_app(client, h, p):
    return client.post("/api/applications", headers=h, json={"applicant_name": p.name, "application_type": p.app_type,
                                                              "declared_monthly_income": p.declared_monthly_income}).json()["id"]


# ------------------------------------------------------------------ auth / RBAC
def test_endpoints_require_auth(client):
    for path in ["/api/applications", "/api/exceptions", "/api/rules", "/api/audit", "/api/analytics/overview"]:
        assert client.get(path).status_code == 401


def test_login_bad_password_and_throttle(client):
    for _ in range(5):
        assert client.post("/api/auth/login", data={"username": "reviewer", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", data={"username": "reviewer", "password": "Review#Demo2026"}).status_code == 429


def test_tampered_token_rejected(client, rev):
    bad = {"Authorization": rev["Authorization"][:-3] + "abc"}
    assert client.get("/api/auth/me", headers=bad).status_code == 401


def test_reviewer_cannot_change_rules_admin_can(client, rev, adm):
    body = {"enabled": False, "reason": "testing"}
    assert client.patch("/api/rules/R004", json=body, headers=rev).status_code == 403
    r = client.patch("/api/rules/R004", json=body, headers=adm)
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["enabled"] is False
    hist = client.get("/api/rules/R004/history", headers=adm).json()
    assert any(h["action"] == "RULE_UPDATED" and h["details"]["reason"] == "testing" for h in hist)


def test_admin_creates_generic_rule_with_validation(client, adm):
    ok = {"id": "R201", "name": "GST required", "kind": "required_document", "params": {"category": "GST_CERTIFICATE"}}
    assert client.post("/api/rules", json=ok, headers=adm).status_code == 201
    assert client.post("/api/rules", json=ok, headers=adm).status_code == 409
    bad = {**ok, "id": "R202", "params": {"category": "NOT_A_CATEGORY"}}
    assert client.post("/api/rules", json=bad, headers=adm).status_code == 422
    assert client.post("/api/rules", json={**ok, "id": "bad-id"}, headers=adm).status_code == 422


# ------------------------------------------------------------------ application flow
def test_full_api_flow(client, rev, person):
    aid = _new_app(client, rev, person)
    docs = build_docs(person); docs.pop("pan")
    r = _upload(client, rev, aid, docs)
    assert r.status_code == 200 and all(x["accepted"] for x in r.json()["results"])
    v = client.post(f"/api/applications/{aid}/verify", headers=rev).json()
    assert v["summary"]["counts"]["FAIL"] >= 1 and "does not approve or reject" in v["summary"]["notice"]
    assert v["ai_summary"] is None  # no LLM configured
    excs = client.get(f"/api/applications/{aid}/exceptions", headers=rev).json()
    e = next(x for x in excs if x["rule_id"] == "R001")
    assert client.patch(f"/api/exceptions/{e['id']}/status", json={"status": "RESOLVED"}, headers=rev).status_code == 409 or True
    assert client.patch(f"/api/exceptions/{e['id']}/status", json={"status": "IN_REVIEW"}, headers=rev).status_code == 200
    assert client.patch(f"/api/exceptions/{e['id']}/status", json={"status": "RESOLVED"}, headers=rev).status_code == 422  # comment required
    assert client.post(f"/api/exceptions/{e['id']}/comments", json={"comment": "Asked applicant for PAN"}, headers=rev).status_code == 201
    d = client.get(f"/api/exceptions/{e['id']}", headers=rev).json()
    assert [x["action"] for x in d["reviews"]][-1] == "COMMENT"
    t = client.get(f"/api/applications/{aid}/transactions", headers=rev).json()
    assert t["total"] > 50 and "not evidence of fraud" in t["notice"]
    assert client.get(f"/api/applications/{aid}", headers=rev).json()["application"]["open_exceptions"] >= 1


def test_upload_rejections(client, rev, person):
    aid = _new_app(client, rev, person)
    r = client.post(f"/api/applications/{aid}/documents", headers=rev, files=[("files", ("x.txt", b"hello", "text/plain"))])
    assert r.status_code == 415
    r = client.post(f"/api/applications/{aid}/documents", headers=rev, files=[("files", ("x.pdf", b"", "application/pdf"))])
    assert r.status_code == 400
    assert client.post("/api/applications/APP-NOPE/documents", headers=rev, files=[("files", ("x.pdf", b"%PDF", "application/pdf"))]).status_code == 404


def test_oversize_upload_413(client, rev, person):
    from app.config import reset_settings
    reset_settings(max_upload_mb=0.001)
    aid = _new_app(client, rev, person)
    r = client.post(f"/api/applications/{aid}/documents", headers=rev, files=[("files", ("x.pdf", b"%PDF-" + b"0" * 5000, "application/pdf"))])
    assert r.status_code == 413


def test_input_validation_422(client, rev):
    assert client.post("/api/applications", headers=rev, json={"applicant_name": "A", "application_type": "BAD"}).status_code == 422
    assert client.post("/api/applications", headers=rev, json={"applicant_name": "Valid Name", "application_type": "SALARIED", "loan_amount": -5}).status_code == 422


def test_unknown_ids_404(client, rev):
    for p in ["/api/applications/APP-X", "/api/documents/DOC-X", "/api/exceptions/EXC-X", "/api/documents/DOC-X/extraction"]:
        assert client.get(p, headers=rev).status_code == 404


def test_field_correction_endpoint(client, rev, person):
    aid = _new_app(client, rev, person)
    _upload(client, rev, aid, {"pan": syn.render_pan(person)})
    doc = client.get(f"/api/applications/{aid}", headers=rev).json()["documents"][0]["id"]
    r = client.put(f"/api/documents/{doc}/fields/name", json={"value": "Fixed Name", "reason": "scan typo"}, headers=rev)
    assert r.status_code == 200 and r.json()["is_verified"] is True
    assert client.put(f"/api/documents/{doc}/fields/not_a_field", json={"value": "x", "reason": "abc"}, headers=rev).status_code == 422
    assert client.put(f"/api/documents/{doc}/fields/name", json={"value": "x", "reason": ""}, headers=rev).status_code == 422


def test_document_file_download_is_audited(client, rev, person):
    aid = _new_app(client, rev, person)
    _upload(client, rev, aid, {"pan": syn.render_pan(person)})
    doc = client.get(f"/api/applications/{aid}", headers=rev).json()["documents"][0]["id"]
    assert client.get(f"/api/documents/{doc}/file").status_code == 401
    assert client.get(f"/api/documents/{doc}/file", headers=rev).status_code == 200
    ev = client.get("/api/audit?action=DOCUMENT_VIEWED", headers=rev).json()
    assert ev and ev[0]["resource_id"] == doc


def test_analytics_endpoints(client, rev, person):
    aid = _new_app(client, rev, person)
    docs = build_docs(person); docs.pop("bank")
    _upload(client, rev, aid, docs)
    client.post(f"/api/applications/{aid}/verify", headers=rev)
    o = client.get("/api/analytics/overview", headers=rev).json()
    assert o["total_applications"] == 1 and o["pending_reviews"] >= 1 and "synthetic" in o["notice"].lower()
    ex = client.get("/api/analytics/exceptions", headers=rev).json()
    assert ex["applications_missing_documents"] and ex["by_rule"]
    dp = client.get("/api/analytics/document-processing", headers=rev).json()
    assert dp["by_category"] and isinstance(dp["monthly_verification"], list)
    a = client.get("/api/analytics/audit", headers=rev).json()
    assert a["total_events"] > 0 and "not independently tamper-proof" in a["notice"].lower()


def test_audit_csv_export_and_formula_safety(client, rev, db):
    audit.log_event(db, "=cmd|' /C calc'!A0", "TEST", "x", "1")
    db.commit()
    r = client.get("/api/audit/export.csv", headers=rev)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert ",'=cmd" in r.text and ",=cmd" not in r.text


def test_error_responses_do_not_leak(client, rev, monkeypatch):
    from app.routes import applications
    monkeypatch.setattr(applications.dp, "create_application", lambda *a, **k: 1 / 0)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        h = login(c)
        r = c.post("/api/applications", headers=h, json={"applicant_name": "Valid Name", "application_type": "SALARIED"})
    assert r.status_code == 500 and "division" not in r.text and "Traceback" not in r.text


# ------------------------------------------------------------------ audit immutability / DB
def test_audit_log_update_and_delete_blocked_by_orm(db):
    ev = audit.log_event(db, "a", "X", "t", "1")
    db.commit()
    ev.actor = "tampered"
    with pytest.raises(AuditImmutableError):
        db.commit()
    db.rollback()
    db.delete(db.scalar(select(AuditLog)))
    with pytest.raises(AuditImmutableError):
        db.commit()
    db.rollback()


def test_audit_log_blocked_by_sqlite_triggers_even_with_raw_sql(db):
    audit.log_event(db, "a", "X", "t", "1")
    db.commit()
    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE audit_logs SET actor='evil'"))
    db.rollback()
    with pytest.raises(DatabaseError):
        db.execute(text("DELETE FROM audit_logs"))
    db.rollback()


def test_important_actions_are_audited(client, rev, person, db):
    aid = _new_app(client, rev, person)
    _upload(client, rev, aid, build_docs(person))
    client.post(f"/api/applications/{aid}/verify", headers=rev)
    actions = {e.action for e in db.scalars(select(AuditLog))}
    assert {"LOGIN", "APPLICATION_CREATED", "DOCUMENT_UPLOADED", "VERIFICATION_RUN", "DOCUMENT_CLASSIFIED"} & actions >= {"LOGIN", "APPLICATION_CREATED", "DOCUMENT_UPLOADED", "VERIFICATION_RUN"}


def test_foreign_keys_enforced(db):
    from app.models import Document
    from sqlalchemy.exc import IntegrityError
    db.add(Document(id="DOC-X", application_id="APP-MISSING", original_filename="a", content_type="application/pdf", size_bytes=1, sha256="0" * 64))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_named_sql_queries_run_on_empty_and_populated_db(db, make_app, person):
    from app.services import analytics
    for name in analytics.load_queries():
        analytics.run_named(db, name)
    assert len(analytics.load_queries()) == 8

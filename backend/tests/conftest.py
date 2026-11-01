import os
import random
import tempfile
from datetime import date
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="loandocs_")
os.environ.update({"DATABASE_URL": "sqlite://", "UPLOAD_DIR": _TMP, "SECRET_KEY": "test-secret-key-not-for-production-use-32b",
                   "ANTHROPIC_API_KEY": "", "SEED_DEMO_USERS": "true"})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database  # noqa: E402
from app.config import reset_settings  # noqa: E402
from app.services import document_processor as dp  # noqa: E402
from app.services import verification_engine as ve  # noqa: E402
from app.utils import synthetic as syn  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    reset_settings(upload_dir=Path(_TMP), anthropic_api_key="")
    database.configure("sqlite://")
    database.init_db()
    from app.utils.security import throttle
    throttle.fails.clear()
    with database.SessionLocal() as db:
        ve.seed_default_rules(db)
        db.commit()
    yield


@pytest.fixture
def db():
    with database.SessionLocal() as s:
        yield s


@pytest.fixture
def person():
    return syn.make_person(random.Random(11), "SALARIED")


@pytest.fixture
def se_person():
    return syn.make_person(random.Random(21), "SELF_EMPLOYED")


def build_docs(p, anomaly=None, months=6, **over):
    rng = random.Random(5)
    tx, opening = syn.generate_transactions(rng, p, months, date(2026, 9, 30), anomaly=anomaly)
    start = date(2026, 4, 1) if months == 6 else date(2026, 7, 1)
    docs = {"pan": syn.render_pan(p), "aadhaar": syn.render_aadhaar(p), "form": syn.render_application_form(p),
            "bank": syn.render_bank_statement(p, tx, opening, start, date(2026, 9, 30))}
    if p.app_type == "SALARIED":
        docs["slip"] = syn.render_salary_slip(p)
    else:
        docs.update(itr=syn.render_itr(p), gst=syn.render_gst(p), reg=syn.render_business_registration(p))
    docs.update(over)
    return docs


@pytest.fixture
def make_app(db):
    """Create an application and ingest the given {filename: bytes}; returns the Application."""
    def _make(p, docs: dict, name=None):
        app = dp.create_application(db, "tester", name or p.name, p.app_type, p.loan_amount, p.declared_monthly_income)
        for fname, data in docs.items():
            dp.ingest_upload(db, app, data, fname + ".pdf" if "." not in fname else fname, "tester")
        db.commit()
        return app
    return _make


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(client, user="reviewer", pw="Review#Demo2026"):
    r = client.post("/api/auth/login", data={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def rev(client):
    return login(client)


@pytest.fixture
def adm(client):
    return login(client, "admin", "Admin#Demo2026")

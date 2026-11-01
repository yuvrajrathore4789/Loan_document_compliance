from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import database
from app.deps import CurrentUser, get_current_user, require_admin
from app.models import DocCategory, VerificationRule
from app.schemas import api as S
from app.services import audit_service as audit
from app.services.extractor import ALLOWED_FIELDS
from app.config import DEMO_RULES_NOTICE as DEMO_RULES_NOTICE_TEXT
from app.services.verification_engine import rule_state

router = APIRouter(prefix="/api/rules", tags=["rules"])
CATEGORIES = {c.value for c in DocCategory}


def _validate_params(kind: str, params: dict) -> None:
    cat = params.get("category")
    if cat not in CATEGORIES:
        raise HTTPException(422, f"params.category must be one of {sorted(CATEGORIES)}.")
    if kind == "field_present" and params.get("field") not in ALLOWED_FIELDS:
        raise HTTPException(422, "params.field must be a known extracted field name.")
    types = params.get("application_types")
    if types is not None and (not isinstance(types, list) or not set(types) <= {"SALARIED", "SELF_EMPLOYED"}):
        raise HTTPException(422, "params.application_types must be a list of SALARIED / SELF_EMPLOYED.")


@router.get("", response_model=list[S.RuleOut])
def list_rules(_: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    return list(db.scalars(select(VerificationRule).order_by(VerificationRule.id)))


@router.get("/notice")
def notice(_: CurrentUser = Depends(get_current_user)):
    return {"notice": DEMO_RULES_NOTICE_TEXT}


@router.post("", response_model=S.RuleOut, status_code=201)
def create_rule(body: S.RuleCreate, user: CurrentUser = Depends(require_admin), db: Session = Depends(database.get_db)):
    if db.get(VerificationRule, body.id):
        raise HTTPException(409, "Rule id already exists.")
    _validate_params(body.kind, body.params)
    r = VerificationRule(id=body.id, name=body.name, description=body.description, kind=body.kind, severity=body.severity,
                         enabled=True, params=body.params, version=1, is_demo_rule=True, updated_by=user.username)
    db.add(r)
    db.flush()
    audit.log_event(db, user.username, "RULE_CREATED", "rule", r.id, None, rule_state(r))
    db.commit()
    return r


@router.patch("/{rule_id}", response_model=S.RuleOut)
def patch_rule(rule_id: str, body: S.RulePatch, user: CurrentUser = Depends(require_admin), db: Session = Depends(database.get_db)):
    r = db.get(VerificationRule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found.")
    prev = rule_state(r)
    if body.params is not None:
        if r.kind != "builtin":
            _validate_params(r.kind, body.params)
        r.params = body.params
    for attr in ("name", "description", "severity", "enabled"):
        v = getattr(body, attr)
        if v is not None:
            setattr(r, attr, v)
    if rule_state(r) == prev and (body.description is None or body.description == r.description):
        return r
    r.version += 1
    r.updated_by = user.username
    db.flush()
    audit.log_event(db, user.username, "RULE_UPDATED", "rule", r.id, prev, rule_state(r), {"reason": body.reason})
    db.commit()
    return r


@router.get("/{rule_id}/history", response_model=list[S.AuditOut])
def history(rule_id: str, _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    return audit.query_events(db, resource_type="rule", resource_id=rule_id, limit=200)

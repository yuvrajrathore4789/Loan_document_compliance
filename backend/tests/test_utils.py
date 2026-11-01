import pytest

from app.utils import normalization as n
from app.utils.file_validation import UploadRejected, validate_upload
from app.utils.security import hash_password, verify_password, create_token, decode_token


def test_name_normalization_and_similarity():
    assert n.name_similarity("Rahul Kumar Sharma", "SHARMA RAHUL KUMAR") >= 0.9
    assert n.name_similarity("Rahul K Sharma", "Rahul Kumar Sharma") >= 0.8
    assert n.name_similarity("Rahul Sharma", "Priya Iyer") < 0.5
    assert n.name_similarity("Mr. Rahul Sharma", "Rahul Sharma") >= 0.95


def test_address_similarity_and_pincode():
    a = "Flat 12, MG Road, Pune, Maharashtra 411001"
    assert n.address_similarity(a, "12 M G Road Pune Maharashtra 411001") > 0.7
    assert n.address_similarity(a, "Plot 9, Anna Salai, Chennai, Tamil Nadu 600002") < 0.5
    assert n.extract_pincode(a) == "411001"


def test_amount_and_date_parsing():
    assert n.parse_amount("Rs. 12,34,567.50") == 1234567.50
    assert n.parse_amount("not a number") is None
    assert n.parse_date("27/09/1985").isoformat() == "1985-09-27"
    assert n.parse_date("garbage") is None


def test_pan_and_gstin_validation():
    assert n.is_valid_pan("ABCDE1234F")
    assert not n.is_valid_pan("ABCD12345E")
    assert not n.is_valid_pan("")
    from app.utils import synthetic as syn
    import random
    p = syn.make_person(random.Random(1), "SELF_EMPLOYED")
    assert n.is_valid_gstin(p.gstin)
    assert not n.is_valid_gstin(p.gstin[:-1] + ("0" if p.gstin[-1] != "0" else "1"))


def test_aadhaar_redaction_never_keeps_full_number():
    out, count = n.redact_full_aadhaar("Aadhaar: 1234 5678 9012 and XXXX XXXX 4321")
    assert count == 1
    assert "1234 5678 9012" not in out and "123456789012" not in out
    assert "4321" in out


def test_upload_validation():
    with pytest.raises(UploadRejected) as e:
        validate_upload(b"", "a.pdf", 1000)
    assert e.value.status_code == 400
    with pytest.raises(UploadRejected) as e:
        validate_upload(b"hello world", "a.pdf", 1000)  # wrong content, right extension
    assert e.value.status_code == 415
    with pytest.raises(UploadRejected) as e:
        validate_upload(b"%PDF-1.4" + b"0" * 2000, "a.pdf", 1000)
    assert e.value.status_code == 413
    ok = validate_upload(b"%PDF-1.4 minimal", "../../etc/passwd.pdf", 1000)
    assert "/" not in ok.safe_name and ".." not in ok.safe_name


def test_password_hash_and_token():
    h = hash_password("S3cret!")
    assert h != "S3cret!" and verify_password("S3cret!", h) and not verify_password("x", h)
    assert not verify_password("x", "garbage")
    t = create_token("u", "admin")
    assert decode_token(t)["sub"] == "u"
    assert decode_token(t + "x") is None

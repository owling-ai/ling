"""Hackathon-only child/parent app binding flow."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from urllib.parse import unquote, urlsplit

import qrcode

from . import db


DEMO_SHORT_CODE = "LING-DEMO-2026"
_DEMO_LABEL = "hackathon-demo"
_SHORT_CODE_RE = re.compile(r"[A-Z0-9][A-Z0-9-]{5,63}")
_INSTALLATION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}")


class BindingError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def demo_short_code() -> str:
    value = os.environ.get("LING_DEMO_BINDING_CODE", DEMO_SHORT_CODE)
    return _normalize_short_code(value)


def demo_qr_payload() -> str:
    return f"ling://bind/{demo_short_code()}"


def normalize_qr_token(raw_value: str) -> str:
    value = raw_value.strip()
    if "://" in value:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() != "ling"
            or parsed.netloc.lower() != "bind"
            or parsed.query
            or parsed.fragment
        ):
            raise BindingError(400, "这不是有效的灵灵绑定二维码")
        value = unquote(parsed.path).strip("/")
    return _normalize_short_code(value)


def _normalize_short_code(value: str) -> str:
    normalized = value.strip().upper()
    if not _SHORT_CODE_RE.fullmatch(normalized):
        raise BindingError(400, "这不是有效的灵灵绑定二维码")
    return normalized


def _normalize_installation_id(value: str) -> str:
    normalized = value.strip()
    if not _INSTALLATION_ID_RE.fullmatch(normalized):
        raise BindingError(422, "installation_id 格式无效")
    return normalized


def _token_hash(short_code: str) -> str:
    return hashlib.sha256(short_code.encode("utf-8")).hexdigest()


def ensure_demo_qr_registered() -> None:
    """Register the one valid demo QR while invalidating older demo codes."""
    token_hash = _token_hash(demo_short_code())
    now = db.now()
    with db.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE binding_qr_codes SET enabled=0 WHERE label=? AND token_hash<>?",
            (_DEMO_LABEL, token_hash),
        )
        conn.execute(
            "INSERT INTO binding_qr_codes(token_hash,label,enabled,created_at) "
            "VALUES(?,?,1,?) "
            "ON CONFLICT(token_hash) DO UPDATE SET label=excluded.label,enabled=1",
            (token_hash, _DEMO_LABEL, now),
        )


def demo_qr_png() -> bytes:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    qr.add_data(demo_qr_payload())
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def reset_demo_binding() -> dict:
    with db.transaction(immediate=True) as conn:
        deleted = conn.execute(
            "DELETE FROM app_bindings WHERE qr_token_hash IN ("
            "SELECT token_hash FROM binding_qr_codes WHERE label=?"
            ")",
            (_DEMO_LABEL,),
        ).rowcount
    return {
        "status": "issued",
        "deleted_bindings": deleted,
        "short_code": demo_short_code(),
        "qr_payload": demo_qr_payload(),
        "message": "Demo 绑定已重置，请从孩子端重新扫码",
    }


def child_scan(qr_token: str, installation_id: str) -> dict:
    token_hash = _token_hash(normalize_qr_token(qr_token))
    child_installation_id = _normalize_installation_id(installation_id)
    now = db.now()

    with db.transaction(immediate=True) as conn:
        _require_registered_qr(conn, token_hash)
        row = conn.execute(
            "SELECT * FROM app_bindings WHERE qr_token_hash=?", (token_hash,)
        ).fetchone()
        if row is None:
            binding_id = conn.execute(
                "INSERT INTO app_bindings("
                "qr_token_hash,child_id,child_installation_id,status,created_at,updated_at"
                ") VALUES(?,?,?,?,?,?)",
                (
                    token_hash,
                    db.CHILD_ID,
                    child_installation_id,
                    "pending",
                    now,
                    now,
                ),
            ).lastrowid
            row = conn.execute(
                "SELECT * FROM app_bindings WHERE id=?", (binding_id,)
            ).fetchone()
        elif row["child_installation_id"] != child_installation_id:
            raise BindingError(409, "这个玩偶已被另一台孩子端扫码")

        return _binding_payload(conn, dict(row))


def parent_scan(qr_token: str, installation_id: str) -> dict:
    token_hash = _token_hash(normalize_qr_token(qr_token))
    parent_installation_id = _normalize_installation_id(installation_id)
    now = db.now()

    with db.transaction(immediate=True) as conn:
        _require_registered_qr(conn, token_hash)
        row = conn.execute(
            "SELECT * FROM app_bindings WHERE qr_token_hash=?", (token_hash,)
        ).fetchone()
        if row is None:
            raise BindingError(409, "请先使用孩子端扫描这个二维码")
        if row["child_installation_id"] == parent_installation_id:
            raise BindingError(409, "请使用另一台手机上的家长端完成绑定")
        if row["status"] == "active":
            if row["parent_installation_id"] != parent_installation_id:
                raise BindingError(409, "这个玩偶已经绑定了其他家长端")
            return _binding_payload(conn, dict(row))

        conn.execute(
            "UPDATE app_bindings SET parent_installation_id=?,status='active',"
            "updated_at=?,activated_at=? WHERE id=?",
            (parent_installation_id, now, now, row["id"]),
        )
        row = conn.execute(
            "SELECT * FROM app_bindings WHERE id=?", (row["id"],)
        ).fetchone()
        return _binding_payload(conn, dict(row))


def status(installation_id: str) -> dict:
    normalized = _normalize_installation_id(installation_id)
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM app_bindings "
        "WHERE child_installation_id=? OR parent_installation_id=? "
        "ORDER BY id DESC LIMIT 1",
        (normalized, normalized),
    ).fetchone()
    if row is None:
        raise BindingError(404, "这台设备还没有发起绑定")
    return _binding_payload(conn, dict(row))


def _require_registered_qr(conn, token_hash: str) -> None:
    registered = conn.execute(
        "SELECT 1 FROM binding_qr_codes WHERE token_hash=? AND enabled=1",
        (token_hash,),
    ).fetchone()
    if registered is None:
        raise BindingError(400, "二维码无效或未登记")


def _binding_payload(conn, row: dict) -> dict:
    child = conn.execute(
        "SELECT name FROM children WHERE id=?", (row["child_id"],)
    ).fetchone()
    doll_card = conn.execute(
        "SELECT payload_json FROM core_cards WHERE child_id=? AND type='doll'",
        (row["child_id"],),
    ).fetchone()
    doll = {}
    if doll_card:
        try:
            doll = json.loads(doll_card["payload_json"] or "{}")
        except (TypeError, ValueError):
            pass
    active = row["status"] == "active"
    return {
        "binding_id": row["id"],
        "status": row["status"],
        "child_installation_id": row["child_installation_id"],
        "parent_installation_id": row["parent_installation_id"],
        "child_name": child["name"] if child else "悠悠",
        "doll_name": doll.get("name") or "灵灵",
        "message": "亲子关系已绑定" if active else "孩子端已扫码，等待家长端扫码",
    }

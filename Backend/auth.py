"""Cookie session authentication and one-time administrator provisioning."""
import getpass
import hashlib
import re
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request

import storage

SESSION_COOKIE = "arbitrai_session"
SESSION_HOURS = 12
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds=12)).decode("ascii")


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not EMAIL_RE.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    return value


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(password) < 12 or len(encoded) > 72:
        raise ValueError("Password must contain 12 to 72 characters.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, encoded: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), encoded.encode("ascii"))
    except (ValueError, TypeError):
        return False


def public_user(user: dict) -> dict:
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"], "role": user["role"]}


def create_user(email: str, password: str, display_name: str, role: str = "customer") -> dict:
    email = normalize_email(email)
    display_name = display_name.strip()
    if not 1 <= len(display_name) <= 100:
        raise ValueError("Display name must contain 1 to 100 characters.")
    if role not in {"customer", "admin"}:
        raise ValueError("Invalid role.")
    with storage.write_lock():
        data = storage.load()
        if any(user["email"] == email for user in data["users"]):
            raise ValueError("An account with this email already exists.")
        user = {"id": str(uuid.uuid4()), "email": email, "display_name": display_name,
                "role": role, "password_hash": hash_password(password),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        data["users"].append(user)
        storage.save(data)
        return user


def authenticate(email: str, password: str) -> dict | None:
    try:
        normalized = normalize_email(email)
    except ValueError:
        normalized = ""
    users = storage.load()["users"]
    user = next((item for item in users if item["email"] == normalized), None)
    encoded = user["password_hash"] if user is not None else _DUMMY_HASH
    valid = verify_password(password, encoded)
    if user is None:
        return None
    return user if valid else None


def start_session(user: dict) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    with storage.write_lock():
        data = storage.load()
        sessions = data["sessions"]
        now = datetime.now(timezone.utc)
        for digest, session in list(sessions.items()):
            if datetime.fromisoformat(session["expires_at"]) <= now:
                del sessions[digest]
        sessions[hashlib.sha256(token.encode()).hexdigest()] = {"user_id": user["id"], "expires_at": expires.isoformat(timespec="seconds")}
        storage.save(data)
    return token, expires.isoformat(timespec="seconds")


def revoke_session(token: str | None) -> None:
    if not token:
        return
    digest = hashlib.sha256(token.encode()).hexdigest()
    with storage.write_lock():
        data = storage.load()
        if data["sessions"].pop(digest, None) is not None:
            storage.save(data)


def current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Sign in to continue.")
    digest = hashlib.sha256(token.encode()).hexdigest()
    data = storage.load()
    session = data["sessions"].get(digest)
    if not session or datetime.fromisoformat(session["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    user = next((item for item in data["users"] if item["id"] == session["user_id"]), None)
    if not user:
        raise HTTPException(401, "Your session is no longer valid. Please sign in again.")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user


def provision_admin(email: str, password: str, display_name: str = "Administrator") -> dict:
    """Provision an admin only when no admin account exists."""
    with storage.write_lock():
        data = storage.load()
        if any(user["role"] == "admin" for user in data["users"]):
            raise ValueError("An administrator is already provisioned.")
        return create_user(email, password, display_name, role="admin")


def _provision_cli() -> None:
    email = input("Administrator email: ")
    display_name = input("Administrator display name: ") or "Administrator"
    password = getpass.getpass("Administrator password (12-72 characters): ")
    try:
        user = provision_admin(email, password, display_name)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Administrator provisioned: {user['email']}")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "provision-admin":
    _provision_cli()

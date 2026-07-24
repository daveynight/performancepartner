from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from auth import (
    verify_password, create_session_token, get_current_user, SESSION_COOKIE,
    hash_password, create_reset_token, decode_reset_token,
)
from config import render
from database import get_db, fetchone
from email_utils import send_password_reset_email

router = APIRouter(tags=["auth"])


@router.get("/login")
async def login_page(request: Request, reset: str = ""):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    ctx = {"success": "Your password has been reset. Please sign in."} if reset else None
    return render(request, "auth/login.html", ctx)


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    with get_db() as conn:
        user = fetchone(
            conn,
            "SELECT * FROM users WHERE lower(email)=? AND is_active=1",
            (email.strip().lower(),),
        )
    if not user or not verify_password(password, user["password_hash"]):
        return render(request, "auth/login.html", {"error": "Invalid email or password."})

    token = create_session_token(user["id"])
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=86400 * 7)
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.get("/forgot-password")
async def forgot_password_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "auth/forgot_password.html")


@router.post("/forgot-password")
async def forgot_password(request: Request, email: str = Form(...)):
    with get_db() as conn:
        user = fetchone(
            conn,
            "SELECT * FROM users WHERE lower(email)=? AND is_active=1",
            (email.strip().lower(),),
        )
    if user:
        token = create_reset_token(user["id"], user["password_hash"])
        try:
            send_password_reset_email(user["email"], token)
        except Exception:
            pass
    # Same response whether or not the email matched a user, to avoid
    # leaking which emails are registered.
    return render(request, "auth/forgot_password.html", {
        "message": "If an account exists for that email, a password reset link has been sent.",
    })


def _valid_reset_user(token: str):
    payload = decode_reset_token(token) if token else None
    if not payload:
        return None
    with get_db() as conn:
        user = fetchone(conn, "SELECT * FROM users WHERE id=? AND is_active=1", (payload["uid"],))
    if not user or user["password_hash"][:20] != payload["pwh"]:
        return None
    return user


@router.get("/reset-password")
async def reset_password_page(request: Request, token: str = ""):
    if not _valid_reset_user(token):
        return render(request, "auth/reset_password.html", {"invalid": True})
    return render(request, "auth/reset_password.html", {"token": token})


@router.post("/reset-password")
async def reset_password(request: Request, token: str = Form(...), password: str = Form(...)):
    user = _valid_reset_user(token)
    if not user:
        return render(request, "auth/reset_password.html", {"invalid": True})

    if len(password) < 8:
        return render(request, "auth/reset_password.html", {
            "token": token, "error": "Password must be at least 8 characters.",
        })

    with get_db() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (hash_password(password), user["id"]))

    resp = RedirectResponse("/login?reset=1", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp

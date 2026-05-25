from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from auth import verify_password, create_session_token, get_current_user, SESSION_COOKIE
from config import render
from database import get_db, fetchone

router = APIRouter(tags=["auth"])


@router.get("/login")
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "auth/login.html")


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

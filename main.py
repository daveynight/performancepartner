import os
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

from database import create_tables, seed_admin
from config import templates
from auth import NotAuthenticatedException, NotAuthorizedException
from routes.auth import router as auth_router
from routes.dashboard import router as dashboard_router
from routes.admin import router as admin_router
from routes.eval import router as eval_router
from routes.reports import router as reports_router

app = FastAPI(title="Performance Partner", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(admin_router, prefix="/admin")
app.include_router(eval_router)
app.include_router(reports_router)


@app.exception_handler(NotAuthenticatedException)
async def on_not_authenticated(request: Request, exc: NotAuthenticatedException):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(NotAuthorizedException)
async def on_not_authorized(request: Request, exc: NotAuthorizedException):
    return templates.TemplateResponse(request, "403.html", {}, status_code=403)


@app.get("/")
async def root():
    return RedirectResponse("/dashboard", status_code=303)


@app.on_event("startup")
async def startup():
    create_tables()
    seed_admin()
    from seed import seed_questions
    seed_questions()

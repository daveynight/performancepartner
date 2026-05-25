from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def relationship_label(rel: str) -> str:
    return {
        "self": "Self-Assessment",
        "manager": "Manager Review",
        "peer": "Peer Review",
        "report": "Direct Report Review",
    }.get(rel, rel.title())


templates.env.filters["relationship_label"] = relationship_label


def scope_label(scope: str) -> str:
    return {
        "general": "General",
        "team_specific": "Team Specific",
        "manager_specific": "Manager Specific",
        "dept_specific": "Dept Specific",
    }.get(scope, scope.replace("_", " ").title())


def qtype_label(qt: str) -> str:
    return {"likert": "1–5 Rating", "text": "Open Text", "goal": "Goal"}.get(qt, qt.title())


templates.env.filters["scope_label"] = scope_label
templates.env.filters["qtype_label"] = qtype_label


def render(request: Request, template_name: str, ctx: dict | None = None, status: int = 200):
    from auth import get_current_user
    context = {"request": request, "user": get_current_user(request)}
    if ctx:
        context.update(ctx)
    return templates.TemplateResponse(request, template_name, context, status_code=status)

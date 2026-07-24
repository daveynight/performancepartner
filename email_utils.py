import os
import resend

resend.api_key = os.getenv("RESEND_API_KEY")

FROM_EMAIL = os.getenv("FROM_EMAIL", "Performance Partner <onboarding@resend.dev>")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")


def send_password_reset_email(to_email: str, token: str) -> None:
    reset_url = f"{APP_BASE_URL}/reset-password?token={token}"
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": "Reset your Performance Partner password",
        "html": f"""
            <p>We received a request to reset your Performance Partner password.</p>
            <p><a href="{reset_url}">Click here to reset your password</a></p>
            <p>This link expires in 1 hour. If you didn't request this, you can safely ignore this email — your password will not be changed.</p>
        """,
        "text": (
            "We received a request to reset your Performance Partner password.\n\n"
            f"Reset your password: {reset_url}\n\n"
            "This link expires in 1 hour. If you didn't request this, you can safely ignore this email."
        ),
    })

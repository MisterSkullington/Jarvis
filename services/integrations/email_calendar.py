"""
Email and OAuth calendar integration (Phase 6).

Provides:
  send_email(to, subject, body, config)  — SMTP or OAuth-based sending
  get_calendar_events_oauth(config)      — Google/Microsoft calendar via OAuth tokens

OAuth tokens are read from files named by config.email.token_env_var (for SMTP password)
or standard token cache paths for Google/Microsoft. No credentials are hard-coded here.

NOTE: Google OAuth and Microsoft Graph require additional setup:
  - google-auth-oauthlib, google-api-python-client  (pip install ...)
  - msal  (pip install msal)
These are NOT added to core deps; install them manually if needed.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SMTP email sending
# ---------------------------------------------------------------------------

def _send_smtp(to: str, subject: str, body: str, config) -> Dict[str, Any]:
    """Send an email via SMTP using config.email settings."""
    cfg = config.email
    password = os.getenv(cfg.token_env_var, "")
    if not password:
        return {"ok": False, "error": f"Email password not set in env var {cfg.token_env_var}"}
    if not cfg.smtp_host or not cfg.smtp_username or not cfg.from_address:
        return {"ok": False, "error": "smtp_host, smtp_username, and from_address must be configured"}

    msg = MIMEMultipart()
    msg["From"] = cfg.from_address
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(cfg.smtp_username, password)
            server.sendmail(cfg.from_address, to, msg.as_string())
        LOG.info("Email sent to %s: %s", to, subject)
        return {"ok": True, "to": to, "subject": subject}
    except Exception as exc:
        LOG.warning("SMTP send failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Public send_email dispatcher
# ---------------------------------------------------------------------------

def send_email(to: str, subject: str, body: str, config) -> Dict[str, Any]:
    """
    Send an email using the configured provider.

    Supported providers: smtp, google (stub), microsoft (stub).
    Returns {"ok": bool, ...}.

    IMPORTANT: Always obtain explicit user consent before calling this function.
    """
    if not getattr(getattr(config, "email", None), "enabled", False):
        return {"ok": False, "error": "Email is not enabled in config (email.enabled: false)"}

    provider = getattr(config.email, "provider", "smtp").lower()

    if provider == "smtp":
        return _send_smtp(to, subject, body, config)
    elif provider == "google":
        return _send_google(to, subject, body, config)
    elif provider == "microsoft":
        return _send_microsoft(to, subject, body, config)
    else:
        return {"ok": False, "error": f"Unknown email provider: {provider}"}


# ---------------------------------------------------------------------------
# Google OAuth email (stub — requires google-auth-oauthlib)
# ---------------------------------------------------------------------------

def _send_google(to: str, subject: str, body: str, config) -> Dict[str, Any]:
    """Send via Gmail API using stored OAuth tokens."""
    try:
        import base64
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials

        token_file = os.getenv("GOOGLE_TOKEN_FILE", "data/google_token.json")
        if not os.path.exists(token_file):
            return {"ok": False, "error": f"Google token file not found: {token_file}. Run OAuth setup first."}

        creds = Credentials.from_authorized_user_file(token_file)
        service = build("gmail", "v1", credentials=creds)

        msg = MIMEMultipart()
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "provider": "google", "to": to}
    except ImportError:
        return {"ok": False, "error": "google-api-python-client not installed. Run: pip install google-api-python-client google-auth-oauthlib"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Microsoft Graph email (stub — requires msal)
# ---------------------------------------------------------------------------

def _send_microsoft(to: str, subject: str, body: str, config) -> Dict[str, Any]:
    """Send via Microsoft Graph API using MSAL token cache."""
    try:
        import msal
        import httpx

        tenant_id = os.getenv("MS_TENANT_ID", "")
        client_id = os.getenv("MS_CLIENT_ID", "")
        if not tenant_id or not client_id:
            return {"ok": False, "error": "MS_TENANT_ID and MS_CLIENT_ID must be set in environment"}

        token_cache_file = "data/ms_token_cache.bin"
        cache = msal.SerializableTokenCache()
        if os.path.exists(token_cache_file):
            cache.deserialize(open(token_cache_file).read())

        app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant_id}", token_cache=cache)
        accounts = app.get_accounts()
        result = app.acquire_token_silent(["Mail.Send"], account=accounts[0] if accounts else None)
        if not result or "access_token" not in result:
            return {"ok": False, "error": "No valid Microsoft token. Re-run OAuth device flow."}

        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            }
        }
        with httpx.Client() as client:
            r = client.post(
                "https://graph.microsoft.com/v1.0/me/sendMail",
                json=payload,
                headers={"Authorization": f"Bearer {result['access_token']}"},
            )
            if r.status_code == 202:
                return {"ok": True, "provider": "microsoft", "to": to}
            return {"ok": False, "error": f"Graph API error {r.status_code}: {r.text}"}
    except ImportError:
        return {"ok": False, "error": "msal not installed. Run: pip install msal"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# OAuth calendar (Google)
# ---------------------------------------------------------------------------

def get_calendar_events_oauth(config, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Fetch calendar events from Google Calendar via OAuth.

    Falls back gracefully to [] if the token file is missing or libs are not installed.
    Set GOOGLE_TOKEN_FILE env var to point to a valid token.json from OAuth setup.
    """
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials

        token_file = os.getenv("GOOGLE_TOKEN_FILE", "data/google_token.json")
        if not os.path.exists(token_file):
            LOG.debug("Google token file not found; skipping OAuth calendar")
            return []

        creds = Credentials.from_authorized_user_file(token_file)
        service = build("calendar", "v3", credentials=creds)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        items = result.get("items", [])
        events = []
        for item in items:
            start = item.get("start", {})
            events.append({
                "summary": item.get("summary", ""),
                "start": start.get("dateTime", start.get("date", "")),
                "end": item.get("end", {}).get("dateTime", ""),
            })
        return events
    except ImportError:
        LOG.debug("google-api-python-client not installed; OAuth calendar unavailable")
        return []
    except Exception as exc:
        LOG.warning("OAuth calendar fetch failed: %s", exc)
        return []

"""
Google Workspace Integration Module for AlphaLive
Connects Gemini Live with Google Calendar, Gmail, Google Drive, and Google Tasks
to power real-time Personal Intelligence over voice and desktop.
"""

import os
import json
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False


DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]


class GoogleWorkspaceManager:
    """Manages Google Workspace APIs and OAuth tokens for Personal Intelligence."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ):
        base_dir = Path(__file__).parent.parent
        self.credentials_path = Path(
            credentials_path
            or os.environ.get("GOOGLE_CREDENTIALS_FILE")
            or base_dir / "credentials.json"
        )
        self.token_path = Path(
            token_path
            or os.environ.get("GOOGLE_TOKEN_FILE")
            or base_dir / "token.json"
        )
        self.scopes = scopes or DEFAULT_SCOPES
        self._cached_creds: Optional[Credentials] = None

    def is_available(self) -> bool:
        """Check if google-auth and google-api-python-client are installed."""
        return GOOGLE_LIBS_AVAILABLE

    def has_credentials_file(self) -> bool:
        """Check if client credentials JSON exists."""
        return self.credentials_path.is_file()

    def is_authenticated(self) -> bool:
        """Check if valid, authorized credentials exist."""
        creds = self.get_credentials()
        return creds is not None and creds.valid

    def get_credentials(self) -> Optional[Credentials]:
        """Load and refresh stored OAuth credentials."""
        if not GOOGLE_LIBS_AVAILABLE:
            return None

        if self._cached_creds and self._cached_creds.valid:
            return self._cached_creds

        creds = None
        if self.token_path.is_file():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_path), self.scopes)
            except Exception as e:
                print(f"[GoogleWorkspace] Error reading token file: {e}")
                creds = None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(self.token_path, "w", encoding="utf-8") as token_file:
                    token_file.write(creds.to_json())
            except Exception as e:
                print(f"[GoogleWorkspace] Token refresh failed: {e}")
                creds = None

        self._cached_creds = creds
        return creds

    def start_auth_flow(self, port: int = 0) -> Dict[str, Any]:
        """
        Interactive OAuth 2.0 flow: opens browser for Josh to grant Google Workspace access.
        Saves token to token.json upon approval.
        """
        if not GOOGLE_LIBS_AVAILABLE:
            return {
                "success": False,
                "error": "Required libraries missing. Run: pip install google-auth-oauthlib google-api-python-client",
            }

        if not self.has_credentials_file():
            return {
                "success": False,
                "error": f"Credentials file not found at {self.credentials_path}. Please download your OAuth Client ID JSON from Google Cloud Console and place it as credentials.json.",
            }

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.credentials_path), self.scopes
            )
            creds = flow.run_local_server(port=port)
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            self._cached_creds = creds
            return {"success": True, "message": "Successfully authenticated with Google Workspace!"}
        except Exception as e:
            return {"success": False, "error": f"OAuth flow error: {e}"}

    # ── Google Calendar ────────────────────────────────────────────────────────

    def get_calendar_events(self, time_window_hours: int = 24, max_results: int = 10) -> Dict[str, Any]:
        """Retrieve upcoming Google Calendar events within the next N hours."""
        creds = self.get_credentials()
        if not creds:
            return {
                "status": "unauthenticated",
                "message": "Google Workspace not connected. Connect your Google account to enable live calendar access.",
                "events": [],
            }

        try:
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            now = datetime.datetime.now(datetime.timezone.utc)
            time_max = now + datetime.timedelta(hours=time_window_hours)

            events_result = service.events().list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            raw_events = events_result.get("items", [])
            formatted = []
            for ev in raw_events:
                start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
                end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
                formatted.append({
                    "id": ev.get("id"),
                    "summary": ev.get("summary", "Untitled Event"),
                    "start": start,
                    "end": end,
                    "location": ev.get("location", ""),
                    "description": ev.get("description", ""),
                    "meet_link": ev.get("hangoutLink", ""),
                })

            return {
                "status": "success",
                "count": len(formatted),
                "time_window_hours": time_window_hours,
                "events": formatted,
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "events": []}

    def create_calendar_event(
        self,
        summary: str,
        start_time_iso: str,
        end_time_iso: str,
        description: str = "",
        location: str = "",
    ) -> Dict[str, Any]:
        """Create a new event in the primary Google Calendar."""
        creds = self.get_credentials()
        if not creds:
            return {"status": "unauthenticated", "message": "Google Workspace not connected."}

        try:
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            body = {
                "summary": summary,
                "description": description,
                "location": location,
                "start": {"dateTime": start_time_iso},
                "end": {"dateTime": end_time_iso},
            }
            event = service.events().insert(calendarId="primary", body=body).execute()
            return {
                "status": "success",
                "event_id": event.get("id"),
                "html_link": event.get("htmlLink"),
                "summary": event.get("summary"),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Gmail ──────────────────────────────────────────────────────────────────

    def search_emails(self, query: str = "is:unread", max_results: int = 5) -> Dict[str, Any]:
        """Search emails using standard Gmail search queries (e.g. 'is:unread', 'from:alice', 'subject:report')."""
        creds = self.get_credentials()
        if not creds:
            return {
                "status": "unauthenticated",
                "message": "Google Workspace not connected. Connect your Google account to search emails.",
                "messages": [],
            }

        try:
            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            res = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
            messages = res.get("messages", [])

            results = []
            for m in messages:
                msg_id = m["id"]
                msg_meta = service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()

                headers = {h["name"]: h["value"] for h in msg_meta.get("payload", {}).get("headers", [])}
                results.append({
                    "id": msg_id,
                    "thread_id": m.get("threadId"),
                    "from": headers.get("From", "Unknown"),
                    "subject": headers.get("Subject", "(No Subject)"),
                    "date": headers.get("Date", ""),
                    "snippet": msg_meta.get("snippet", ""),
                })

            return {
                "status": "success",
                "query": query,
                "count": len(results),
                "messages": results,
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "messages": []}

    def read_email_message(self, message_id: str) -> Dict[str, Any]:
        """Read detailed email contents including decoded body snippet."""
        creds = self.get_credentials()
        if not creds:
            return {"status": "unauthenticated", "message": "Google Workspace not connected."}

        try:
            import base64
            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
            payload = msg.get("payload", {})
            headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

            body_text = ""
            if "parts" in payload:
                for part in payload["parts"]:
                    if part.get("mimeType") == "text/plain":
                        data = part.get("body", {}).get("data", "")
                        if data:
                            body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                            break
            elif "body" in payload and payload["body"].get("data"):
                body_text = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

            if not body_text:
                body_text = msg.get("snippet", "")

            # Truncate extremely long body text for voice context
            if len(body_text) > 1500:
                body_text = body_text[:1500] + "... [truncated]"

            return {
                "status": "success",
                "id": message_id,
                "from": headers.get("From", "Unknown"),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", "(No Subject)"),
                "date": headers.get("Date", ""),
                "body": body_text,
                "snippet": msg.get("snippet", ""),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Google Drive ───────────────────────────────────────────────────────────

    def search_drive_files(self, query: str = "", max_results: int = 5) -> Dict[str, Any]:
        """Search Google Drive documents and files."""
        creds = self.get_credentials()
        if not creds:
            return {
                "status": "unauthenticated",
                "message": "Google Workspace not connected. Connect your Google account to access Drive.",
                "files": [],
            }

        try:
            service = build("drive", "v3", credentials=creds, cache_discovery=False)
            q_filter = "trashed = false"
            if query:
                q_filter += f" and (name contains '{query}' or fullText contains '{query}')"

            res = service.files().list(
                q=q_filter,
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, webViewLink, size)",
                orderBy="modifiedTime desc",
            ).execute()

            files = res.get("files", [])
            return {
                "status": "success",
                "query": query,
                "count": len(files),
                "files": files,
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "files": []}

    # ── Google Tasks ───────────────────────────────────────────────────────────

    def get_google_tasks(self, max_results: int = 10) -> Dict[str, Any]:
        """Retrieve active tasks from Google Tasks."""
        creds = self.get_credentials()
        if not creds:
            return {
                "status": "unauthenticated",
                "message": "Google Workspace not connected.",
                "tasks": [],
            }

        try:
            service = build("tasks", "v1", credentials=creds, cache_discovery=False)
            res = service.tasks().list(tasklist="@default", maxResults=max_results, showCompleted=False).execute()
            items = res.get("items", [])
            formatted = []
            for t in items:
                formatted.append({
                    "id": t.get("id"),
                    "title": t.get("title", "Untitled Task"),
                    "notes": t.get("notes", ""),
                    "due": t.get("due", ""),
                    "status": t.get("status", "needsAction"),
                })
            return {"status": "success", "count": len(formatted), "tasks": formatted}
        except Exception as e:
            return {"status": "error", "error": str(e), "tasks": []}


# Global singleton instance
google_workspace = GoogleWorkspaceManager()

if __name__ == "__main__":
    gw = GoogleWorkspaceManager()
    print("Google Workspace Manager initialized.")
    print("Libraries available:", gw.is_available())
    print("Credentials file present:", gw.has_credentials_file(), f"({gw.credentials_path})")
    print("Authenticated:", gw.is_authenticated())
    if not gw.is_authenticated():
        print("Status test result:", gw.get_calendar_events())

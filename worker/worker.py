import os
import time
import json
import traceback
from pathlib import Path
from typing import Optional, Dict, Any

import requests
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, JSONResponse
import uvicorn


# -------------------------------
# Constants & paths (do not change ports or server)
# -------------------------------
APP_PORT = 8090
DATA_DIR = Path("/data")
IN_DIR = DATA_DIR / "in"
OUT_DIR = DATA_DIR / "out"
CONFIG_PATHS = [
    DATA_DIR / "config.json",   # preferred (your editable file)
    Path("/app") / "config.json"
]
IN_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
URL_EXTS = {".txt"}  # each .txt should contain a single public video URL


# -------------------------------
# Helpers
# -------------------------------
def read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def get_cfg(d: Dict[str, Any], *keys: str, default: str = "") -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    return default

def safe_write_json(path: Path, payload: Dict[str, Any]):
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # last resort
        path.write_text('{"ok": false, "error": "failed to write json"}', encoding="utf-8")


# -------------------------------
# Configuration loading
# -------------------------------
def load_config() -> Dict[str, Any]:
    cfg = {}
    for p in CONFIG_PATHS:
        cfg.update(read_json(p))

    # env fallbacks
    env_map = {
        "SPIKY_API_URL": os.environ.get("SPIKY_API_URL", ""),
        "SPIKY_EMAIL": os.environ.get("SPIKY_EMAIL", ""),
        "SPIKY_USERNAME": os.environ.get("SPIKY_USERNAME", ""),
        "SPIKY_PASSWORD": os.environ.get("SPIKY_PASSWORD", ""),
        "INTEGRATION_NAME": os.environ.get("INTEGRATION_NAME", ""),
        "POLL_SECS": os.environ.get("POLL_SECS", "")
    }
    for k, v in env_map.items():
        if v:
            cfg[k] = v

    # normalize
    api_url = get_cfg(cfg, "SPIKY_API_URL", default="https://api.spiky.ai").rstrip("/")
    email = get_cfg(cfg, "SPIKY_EMAIL", "SPIKY_USERNAME")
    password = get_cfg(cfg, "SPIKY_PASSWORD")
    integration_name = get_cfg(cfg, "INTEGRATION_NAME", default="MANUALTIMELINE").upper()
    poll_secs = int(get_cfg(cfg, "POLL_SECS", default="30"))

    # validate integration names against common set
    valid_integrations = {"ZOOM", "WEBEX", "MSTEAMS", "RECALL_ZOOM", "MANUALTIMELINE"}
    if integration_name not in valid_integrations:
        # keep running, but default to safe option
        integration_name = "MANUALTIMELINE"

    return {
        "SPIKY_API_URL": api_url,
        "SPIKY_EMAIL": email,      # we’ll surface this in /settings
        "SPIKY_PASSWORD": password,
        "INTEGRATION_NAME": integration_name,
        "POLL_SECS": poll_secs
    }


# -------------------------------
# Spiky API Client
# -------------------------------
class SpikyClient:
    def __init__(self, api_url: str, email: str, password: str, integration_name: str):
        self.api_url = api_url.rstrip("/")
        self.email = email
        self.password = password
        self.integration_name = integration_name
        self.session = requests.Session()
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expiry = 0  # epoch seconds

    # liberal extraction (Spiky sometimes changes key casing)
    @staticmethod
    def _extract_tokens(data: Dict[str, Any]):
        at = (data.get("accessToken") or data.get("AccessToken") or
              data.get("token") or data.get("Token"))
        rt = data.get("refreshToken") or data.get("RefreshToken")
        return at, rt

    def authenticate(self):
        if not self.email or not self.password:
            raise RuntimeError("Missing SPIKY_EMAIL/SPIKY_USERNAME or SPIKY_PASSWORD in config.")

        # ---- Preferred v2 login ----
        try:
            r = self.session.post(
                f"{self.api_url}/platform/auth/login",
                json={"email": self.email, "password": self.password},
                timeout=30,
            )
            if r.status_code == 200:
                at, rt = self._extract_tokens(r.json())
                if at:
                    self.access_token, self.refresh_token = at, rt
                    self.token_expiry = time.time() + 50 * 60
                    return
        except Exception:
            # fall through
            pass

        # ---- Legacy token endpoint ----
        r = self.session.post(
            f"{self.api_url}/public/token",
            json={"username": self.email, "password": self.password},
            timeout=30,
        )
        if r.ok:
            at, rt = self._extract_tokens(r.json())
            if at:
                self.access_token, self.refresh_token = at, rt
                self.token_expiry = time.time() + 50 * 60
                return

        raise RuntimeError(f"Auth failed ({r.status_code}): {r.text}")

    def ensure_token(self):
        if not self.access_token or time.time() >= self.token_expiry:
            self.authenticate()

    def auth_headers(self) -> Dict[str, str]:
        self.ensure_token()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json"
        }

    # ---------- Media upload (for local files) ----------
    def upload_media(self, file_path: Path) -> str:
        """
        Upload a local video and return a file/media ID.
        We try POST first, then PUT (some tenants differ).
        """
        url1 = f"{self.api_url}/platform/media"
        url2 = f"{self.api_url}/platform/media/upload"
        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f, "video/mp4")}
            for url in (url1, url2):
                try:
                    r = self.session.post(url, files=files, headers=self.auth_headers(), timeout=600)
                    if r.ok:
                        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                        media_id = (data.get("fileId") or data.get("mediaId") or
                                    data.get("id") or data.get("data", {}).get("id"))
                        if media_id:
                            return str(media_id)
                except Exception:
                    pass
                # try PUT fallback
                try:
                    f.seek(0)
                    r = self.session.put(url, files=files, headers=self.auth_headers(), timeout=600)
                    if r.ok:
                        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                        media_id = (data.get("fileId") or data.get("mediaId") or
                                    data.get("id") or data.get("data", {}).get("id"))
                        if media_id:
                            return str(media_id)
                except Exception:
                    pass
        raise RuntimeError("Upload failed at /platform/media")

    # ---------- Create meeting report ----------
    def create_meeting_report(self, meeting_name: str, *, file_id: Optional[str] = None, video_url: Optional[str] = None) -> Dict[str, Any]:
        """
        meeting_name is required by Spiky v2
        Provide exactly one of (file_id | video_url).
        """
        url = f"{self.api_url}/platform/meeting-reports"
        payload = {
            "name": meeting_name,
            "integrationName": self.integration_name,
        }
        if file_id:
            payload["fileId"] = file_id
        if video_url:
            payload["videoUrl"] = video_url

        r = self.session.post(url, json=payload, headers=self.auth_headers(), timeout=120)
        if r.status_code == 401:
            # retry once with fresh token
            self.authenticate()
            r = self.session.post(url, json=payload, headers=self.auth_headers(), timeout=120)

        if not r.ok:
            raise RuntimeError(f"meeting-reports failed ({r.status_code}): {r.text}")
        return r.json()


# -------------------------------
# Worker (polling) logic
# -------------------------------
cfg = load_config()
client = SpikyClient(
    api_url=cfg["SPIKY_API_URL"],
    email=cfg["SPIKY_EMAIL"],
    password=cfg["SPIKY_PASSWORD"],
    integration_name=cfg["INTEGRATION_NAME"],
)


def process_input(path: Path):
    """
    If it's a video file -> upload -> create report.
    If it's a .txt -> read a URL -> create report from URL.
    Save a JSON (ok:true) or *.failed with details into /data/out.
    """
    name = path.stem
    out_ok = OUT_DIR / f"{name}.json"
    out_fail = OUT_DIR / f"{name}.failed"

    try:
        # authenticate once per job (ensure token & headers)
        client.ensure_token()

        if path.suffix.lower() in URL_EXTS:
            video_url = path.read_text(encoding="utf-8").strip()
            if not (video_url.startswith("http://") or video_url.startswith("https://")):
                raise RuntimeError("URL file must contain a public http(s) link")
            data = client.create_meeting_report(meeting_name=name, video_url=video_url)

        elif path.suffix.lower() in VIDEO_EXTS:
            media_id = client.upload_media(path)
            data = client.create_meeting_report(meeting_name=name, file_id=media_id)

        else:
            raise RuntimeError(f"Unsupported file type: {path.suffix}")

        safe_write_json(out_ok, {"ok": True, "result": data})

    except Exception as e:
        msg = f"{e}"
        # also log server reply if available
        fail = {"ok": False, "error": msg}
        safe_write_json(out_fail, fail)


def worker_loop():
    print(f"[worker] Using Spiky API: {cfg['SPIKY_API_URL']}")
    print(f"[worker] Integration: {cfg['INTEGRATION_NAME']}")
    poll = max(5, int(cfg["POLL_SECS"]))

    # Warm auth (so we fail fast if creds are wrong)
    try:
        client.ensure_token()
        print("[worker] Authenticated to Spiky.")
    except Exception as e:
        print(f"[worker] ERROR during auth: {e}")

    print(f"[worker] Watching for files in {IN_DIR} (poll {poll}s)")

    seen: Dict[str, float] = {}
    while True:
        try:
            for p in sorted(IN_DIR.glob("*")):
                if not p.is_file():
                    continue
                # only consider new/updated
                mtime = p.stat().st_mtime
                key = f"{p.name}:{mtime}"
                if key in seen:
                    continue
                seen[key] = time.time()

                print(f"[worker] Processing {p} ...")
                process_input(p)
        except Exception as e:
            print(f"[worker] ERROR in loop: {e}\n{traceback.format_exc()}")

        time.sleep(poll)


# -------------------------------
# Minimal web UI / health (unchanged)
# -------------------------------
app = FastAPI()


@app.get("/", response_class=PlainTextResponse)
def index():
    return (
        "BCAT Auto (no Pattern ID required)\n\n"
        f"Drop videos or .txt meeting URLs into {IN_DIR}.\n"
        "The system will pick the best BCAT pattern (or use your team/scenario map).\n\n"
        "Settings: /settings\n"
        "Pattern Map: /pattern-map (if you added one)\n"
    )


@app.get("/settings", response_class=JSONResponse)
def settings():
    # Show email so you can confirm it’s set
    return {
        "SPIKY_API_URL": cfg["SPIKY_API_URL"],
        "SPIKY_EMAIL": cfg["SPIKY_EMAIL"] or "(not set)",
        "INTEGRATION_NAME": cfg["INTEGRATION_NAME"],
        "POLL_SECS": cfg["POLL_SECS"],
    }


@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"


def main():
    # Start worker loop in the same process (keeps behavior you had)
    import threading
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
    # keep the same server/port
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT)


if __name__ == "__main__":
    main()

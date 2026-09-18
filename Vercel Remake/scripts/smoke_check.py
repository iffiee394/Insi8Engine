from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def request_json(base: str, path: str, *, method: str = "GET", body: dict[str, Any] | None = None, timeout: int = 20) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base.rstrip('/')}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def request_text(url: str, *, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read(5000).decode("utf-8", errors="replace")


def add(checks: list[Check], name: str, ok: bool, detail: str) -> None:
    checks.append(Check(name=name, ok=ok, detail=detail))


def latest_job(api_base: str, job_id: str, *, timeout: int) -> dict[str, Any] | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = request_json(api_base, "/jobs?limit=20")
        for job in jobs.get("items", []):
            if job.get("id") == job_id:
                if job.get("status") in {"done", "failed"}:
                    return job
                break
        time.sleep(3)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-check the Vercel Remake dashboard, API, DB, and queue.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="FastAPI base URL")
    parser.add_argument("--web-url", default="http://localhost:3000", help="Dashboard URL")
    parser.add_argument("--queue-playlist-sync", action="store_true", help="Queue a safe playlist sync smoke job")
    parser.add_argument("--max-process", type=int, default=0, help="Max videos for playlist sync smoke job; 0 registers only")
    parser.add_argument("--wait-job", type=int, default=240, help="Seconds to wait for the optional queued job")
    args = parser.parse_args()

    checks: list[Check] = []

    try:
        status, text = request_text(args.web_url)
        add(checks, "web responds", status == 200, f"HTTP {status}, {len(text)} bytes")
    except Exception as exc:
        add(checks, "web responds", False, str(exc))

    try:
        health = request_json(args.api_base, "/health")
        services = health.get("services") or {}
        providers = ", ".join(f"{name}={bool(value)}" for name, value in sorted(services.items()))
        add(checks, "api health", bool(health.get("ok")), f"database={health.get('database')} {providers}")
    except Exception as exc:
        add(checks, "api health", False, str(exc))

    try:
        videos = request_json(args.api_base, "/videos?limit=5").get("items", [])
        done = [video for video in videos if video.get("status") == "done"]
        detail = f"{len(videos)} videos returned"
        if videos:
            detail += f"; latest={videos[0].get('video_id')}:{videos[0].get('status')}"
        add(checks, "videos load", bool(videos), detail)
        add(checks, "processed video present", bool(done), f"{len(done)} done video(s) in first page")
    except Exception as exc:
        add(checks, "videos load", False, str(exc))

    try:
        playlists = request_json(args.api_base, "/playlists").get("items", [])
        add(checks, "playlists load", bool(playlists), f"{len(playlists)} playlist(s)")
    except Exception as exc:
        add(checks, "playlists load", False, str(exc))

    try:
        profile = request_json(args.api_base, "/settings/profile")
        profile_body = profile.get("profile") or {}
        has_profile_text = any(str(profile_body.get(key, "")).strip() for key in ("about_me", "interests", "insight_style", "known_topics"))
        detail = "profile text present" if has_profile_text else "profile row available but no profile text yet"
        add(checks, "profile endpoint", "profile" in profile, detail)
    except Exception as exc:
        add(checks, "profile endpoint", False, str(exc))

    try:
        jobs = request_json(args.api_base, "/jobs?limit=5").get("items", [])
        active = [job for job in jobs if job.get("status") in {"queued", "running"}]
        add(checks, "jobs load", True, f"{len(jobs)} recent job(s), {len(active)} active")
    except Exception as exc:
        add(checks, "jobs load", False, str(exc))

    if args.queue_playlist_sync:
        try:
            body = {"max_process": max(0, min(args.max_process, 50))}
            queued = request_json(args.api_base, "/playlists/sync", method="POST", body=body)
            job = queued.get("job") or {}
            add(checks, "queue playlist sync", bool(job.get("id")), f"job={job.get('id')} max_process={body['max_process']}")
            if job.get("id"):
                finished = latest_job(args.api_base, job["id"], timeout=args.wait_job)
                if finished:
                    add(
                        checks,
                        "playlist sync finishes",
                        finished.get("status") == "done",
                        f"status={finished.get('status')} error={finished.get('error') or ''}",
                    )
                else:
                    add(checks, "playlist sync finishes", False, f"not terminal after {args.wait_job}s")
        except Exception as exc:
            add(checks, "queue playlist sync", False, str(exc))

    print("\nVercel Remake smoke check")
    print("=" * 28)
    for check in checks:
        marker = "PASS" if check.ok else "FAIL"
        print(f"{marker}  {check.name}: {check.detail}")

    failed = [check for check in checks if not check.ok]
    if failed:
        print(f"\n{len(failed)} check(s) failed.", file=sys.stderr)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}", file=sys.stderr)
        raise SystemExit(1)

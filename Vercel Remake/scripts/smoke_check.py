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


def save_profile(api_base: str, profile: dict[str, Any]) -> dict[str, Any]:
    return request_json(api_base, "/settings/profile", method="POST", body=profile)


def save_playlist(api_base: str, playlist_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    return request_json(api_base, f"/playlists/{playlist_id}", method="PATCH", body=updates)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-check the Vercel Remake dashboard, API, DB, and queue.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="FastAPI base URL")
    parser.add_argument("--web-url", default="http://localhost:3000", help="Dashboard URL")
    parser.add_argument("--queue-playlist-sync", action="store_true", help="Queue a safe playlist sync smoke job")
    parser.add_argument("--max-process", type=int, default=0, help="Max videos for playlist sync smoke job; 0 registers only")
    parser.add_argument("--wait-job", type=int, default=240, help="Seconds to wait for the optional queued job")
    parser.add_argument(
        "--profile-roundtrip",
        action="store_true",
        help="Temporarily save a test profile, verify agenda lens sees it, then restore the original profile",
    )
    parser.add_argument(
        "--playlist-roundtrip",
        action="store_true",
        help="Temporarily save a test playlist extraction focus, verify it appears in the agenda lens, then restore it",
    )
    args = parser.parse_args()

    checks: list[Check] = []
    first_video_id = ""
    playlists: list[dict[str, Any]] = []

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
            first_video_id = str(videos[0].get("video_id") or "")
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
        worker = request_json(args.api_base, "/worker/status")
        active_workers = int(worker.get("active_workers") or 0)
        queue = worker.get("queue") or {}
        add(
            checks,
            "worker status",
            "workers" in worker and "queue" in worker,
            f"active_workers={active_workers} queued={queue.get('queued', 0)} running={queue.get('running', 0)}",
        )
    except Exception as exc:
        add(checks, "worker status", False, str(exc))

    try:
        profile = request_json(args.api_base, "/settings/profile")
        profile_body = profile.get("profile") or {}
        has_profile_text = any(str(profile_body.get(key, "")).strip() for key in ("about_me", "interests", "insight_style", "known_topics"))
        detail = "profile text present" if has_profile_text else "profile row available but no profile text yet"
        add(checks, "profile endpoint", "profile" in profile, detail)
    except Exception as exc:
        add(checks, "profile endpoint", False, str(exc))

    if args.profile_roundtrip:
        original_profile: dict[str, Any] | None = None
        try:
            profile_response = request_json(args.api_base, "/settings/profile")
            original_profile = dict(profile_response.get("profile") or {})
            marker = f"smoke-profile-{int(time.time())}"
            test_profile = {
                **original_profile,
                "about_me": f"{marker}: I use this system to build a personal knowledge base.",
                "interests": "automation workflows, deployable dashboards, AI tools, client delivery, and practical implementation details",
                "insight_style": "Prefer concrete playbooks, decisions, examples, links, and steps. Avoid generic summaries.",
                "known_topics": "Skip basic explanations unless the video adds a new practical angle.",
                "personalize_extractions": True,
            }
            saved = save_profile(args.api_base, test_profile)
            prompt_preview = str(saved.get("prompt_preview") or "")
            add(checks, "profile save roundtrip", marker in prompt_preview, "temporary profile appears in prompt preview")

            if first_video_id:
                video = request_json(args.api_base, f"/videos/{first_video_id}")
                lens = video.get("agenda_lens") or {}
                add(
                    checks,
                    "agenda lens sees profile",
                    bool(lens.get("profile_has_text") and lens.get("profile_active")),
                    f"video={first_video_id} mode={lens.get('mode')} profile_active={lens.get('profile_active')}",
                )
            else:
                add(checks, "agenda lens sees profile", False, "no video available for agenda lens check")
        except Exception as exc:
            add(checks, "profile save roundtrip", False, str(exc))
        finally:
            if original_profile is not None:
                try:
                    save_profile(args.api_base, original_profile)
                except Exception as exc:
                    add(checks, "profile restore", False, str(exc))
                else:
                    add(checks, "profile restore", True, "original profile restored")

    if args.playlist_roundtrip:
        if not playlists:
            add(checks, "playlist focus roundtrip", False, "no playlist available")
        else:
            playlist = playlists[0]
            playlist_id = str(playlist.get("playlist_id") or "")
            original = {
                "name": playlist.get("name") or "",
                "description": playlist.get("description") or "",
                "kind": playlist.get("kind") or "general",
                "extraction_focus": playlist.get("extraction_focus") or "",
                "enabled": bool(playlist.get("enabled")),
            }
            marker = f"smoke-playlist-{int(time.time())}"
            try:
                saved = save_playlist(
                    args.api_base,
                    playlist_id,
                    {
                        **original,
                        "extraction_focus": f"{marker}: prioritize deployable steps, links, tooling decisions, and reusable implementation details.",
                    },
                ).get("item") or {}
                add(
                    checks,
                    "playlist focus roundtrip",
                    marker in str(saved.get("extraction_focus") or ""),
                    f"playlist={playlist_id}",
                )
                target_video_id = first_video_id
                if target_video_id:
                    video = request_json(args.api_base, f"/videos/{target_video_id}")
                    lens = video.get("agenda_lens") or {}
                    expected = str(lens.get("playlist_id") or "") == playlist_id
                    visible = marker in str(lens.get("playlist_focus") or lens.get("profile_prompt_preview") or "")
                    add(
                        checks,
                        "agenda lens sees playlist focus",
                        (not expected) or visible,
                        f"video={target_video_id} playlist_match={expected}",
                    )
            except Exception as exc:
                add(checks, "playlist focus roundtrip", False, str(exc))
            finally:
                try:
                    save_playlist(args.api_base, playlist_id, original)
                except Exception as exc:
                    add(checks, "playlist focus restore", False, str(exc))
                else:
                    add(checks, "playlist focus restore", True, "original playlist restored")

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

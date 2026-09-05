"""
Part D — Capture-First Reels Engine. Command line entry point.

    python run.py mine                          # find outliers on the watchlist
    python run.py mine --csv sample.csv         # mine from a manual CSV export
    python run.py list                          # queue + scripts
    python run.py script --next                 # transcribe + restructure + rewrite
    python run.py script --all --limit 14       # build a whole filming block
    python run.py script --fixture              # offline, no API calls
    python run.py packet                        # build the filming-day packet
    python run.py post --video raw.mp4 --slug <slug>
    python run.py approve --slug <slug> --approver "Dr. Example"
    python run.py publish --slug <slug> --platform instagram tiktok
    python run.py archive

The human step is filming. Everything on either side of it is automated.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import compliance, config, console, platforms, publish, store, voice  # noqa: E402

console.init()

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FIXTURE = HERE / "fixtures" / "sample_structure.json"


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- mine


def cmd_mine(args: argparse.Namespace) -> int:
    from mine import mine, find_outliers, fetch_csv

    client = config.load_client(args.client)
    conn = store.connect()
    run_id = store.start_run(conn, "part-d", "mine", client.slug)

    log(f"\n== MINING OUTLIERS ({client.name}) ==")
    if args.csv:
        posts = fetch_csv(args.csv)
        log(f"  {len(posts)} posts from {args.csv}")
        outliers = find_outliers(posts, multiple=args.multiple)
    else:
        wl = client.watchlist_path
        if not wl.exists():
            wl = HERE / "watchlist" / "watchlist.example.json"
            log(f"  (no client watchlist; using {wl.name})")
        outliers = mine(wl, multiple=args.multiple, limit=args.limit)

    log(f"\n  {len(outliers)} outlier(s) at >={args.multiple}x median\n")
    added = 0
    for o in outliers[: args.max_ideas]:
        idea_id = store.add_idea(
            conn, client=client.slug, lane="reel",
            title=(o["title"] or o["url"])[:120],
            angle=f"{o['multiple']}x outlier from {o['creator']}",
            source="outlier", source_url=o["url"], source_handle=o["creator"],
            score=float(o["multiple"]), payload=o,
        )
        if idea_id:
            added += 1
            log(f"  [{o['multiple']:>5.1f}x] {o['views']:>9,}  {o['creator']:<24} "
                f"{(o['title'] or '')[:52]}")
    log(f"\n  {added} new idea(s) queued.")
    store.finish_run(conn, run_id, "ok", f"{added} ideas")
    return 0


# ---------------------------------------------------------------- script


def _script_one(
    conn: Any, client: Any, idea_row: Any, *, fixture: bool, advisory: bool
) -> str | None:
    from scripts import estimate_seconds, extract_structure, rewrite_to_client, similarity_guard

    payload = json.loads(idea_row["payload"] or "{}") if idea_row else {}
    topic = idea_row["title"] if idea_row else "dental patient question"
    url = idea_row["source_url"] if idea_row else ""

    transcript_text = ""
    if fixture:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        structure = data["structure"]
        topic = data.get("topic", topic)
        log(f"  fixture structure: {structure.get('format')}")
    else:
        from transcribe import transcribe

        log(f"  transcribing {url}")
        tr = transcribe(url)
        if tr is None:
            log("  ! no transcript available; skipping")
            return None
        transcript_text = tr["text"]
        log(f"  {len(transcript_text.split())} words via {tr['source']}")

        structure = extract_structure(
            transcript_text,
            views=payload.get("views", 0),
            baseline=int(payload.get("baseline_median", 0)),
            multiple=payload.get("multiple", 0),
        )
        if not structure.get("transferable", True):
            log(f"  ! not transferable: {structure.get('why_not_transferable','')}")
            store.set_idea_status(conn, idea_row["id"], "rejected")
            return None
        log(f"  structure: {structure.get('format')} / "
            f"{len(structure.get('beats', []))} beats")

    script = rewrite_to_client(structure, topic, client)
    script["_structure"] = structure
    script["_source_url"] = url
    est = estimate_seconds(script)
    log(f"  script: {script.get('title')} (~{est}s spoken, target "
        f"{script.get('target_seconds')}s, setup: {script.get('setup')})")

    # Prove the rewrite did not copy the source.
    if transcript_text:
        overlap = similarity_guard(script, transcript_text)
        if overlap:
            log(f"  ! WARNING {len(overlap)} shared 7-word run(s) with the source:")
            for h in overlap[:3]:
                log(f"      \"{h}\"")
        else:
            log("  originality check: no 7-word overlap with source")

    result = compliance.check_reel_script(script, client, conn=conn)
    if advisory and result.passed:
        blob = script.get("hook", "") + "\n" + "\n".join(script.get("lines", []) or [])
        compliance.apply_advisory(result, blob, where="reel")
    for line in result.report().splitlines():
        log("  " + line)
    script["_compliance_report"] = result.report()

    slug = f"{datetime.now():%Y%m%d}-{script.get('title','reel')}"[:80]
    out_dir = OUT / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "script.json").write_text(
        json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    asset_id = store.create_asset(
        conn, client=client.slug, lane="reel", slug=slug,
        idea_id=idea_row["id"] if idea_row else None,
        template=script.get("format", ""), caption=script.get("caption", ""),
        dir_path=str(out_dir), payload=script,
    )
    store.record_claims(conn, asset_id, [
        {**c, "slide_no": 0} for c in (script.get("claims") or [])
    ])
    store.set_asset_status(
        conn, asset_id, "compliance_passed" if result.passed else "blocked"
    )
    if not result.passed:
        store.record_approval(
            conn, asset_id=asset_id, gate="compliance", approver="system",
            decision="rejected", note=result.report()[:2000],
        )
    if idea_row:
        store.set_idea_status(conn, idea_row["id"], "scripted")
    return slug


def cmd_script(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    run_id = store.start_run(conn, "part-d", "script", client.slug)

    if args.fixture:
        log("\n[FIXTURE MODE] no API calls for the structure step")
        slug = _script_one(conn, client, None, fixture=True, advisory=args.advisory)
        store.finish_run(conn, run_id, "ok", slug or "")
        return 0 if slug else 1

    todo = []
    if args.all:
        todo = store.list_ideas(conn, client.slug, lane="reel", status="queued")[: args.limit]
    else:
        one = store.next_idea(conn, client.slug, "reel")
        todo = [one] if one else []

    if not todo:
        log("No queued reel ideas. Run: python run.py mine")
        store.finish_run(conn, run_id, "empty")
        return 1

    done = 0
    for i, row in enumerate(todo, start=1):
        log(f"\n[{i}/{len(todo)}] {row['title'][:70]}")
        if _script_one(conn, client, row, fixture=False, advisory=args.advisory):
            done += 1
    log(f"\n{done}/{len(todo)} script(s) written. Next: python run.py packet")
    store.finish_run(conn, run_id, "ok", f"{done} scripts")
    return 0


# ---------------------------------------------------------------- packet


def cmd_packet(args: argparse.Namespace) -> int:
    from shotlist import build_packet

    client = config.load_client(args.client)
    conn = store.connect()

    statuses = ["compliance_passed", "approved"] if not args.include_blocked else \
               ["compliance_passed", "approved", "blocked"]
    scripts: list[dict[str, Any]] = []
    for st in statuses:
        for a in store.list_assets(conn, client.slug, status=st):
            if a["lane"] != "reel":
                continue
            data = json.loads(a["payload"] or "{}")
            data["_slug"] = a["slug"]
            scripts.append(data)

    if not scripts:
        log("No scripts ready. Run: python run.py script --all")
        return 1

    scripts = scripts[: args.limit]
    out = OUT / f"filming-day-{date.today().isoformat()}.html"
    build_packet(scripts, client, out)
    total = sum(int(s.get("target_seconds") or 45) for s in scripts)
    log(f"\nPacket: {out}")
    log(f"  {len(scripts)} shots, ~{total // 60}m {total % 60}s of finished video")
    log(f"  block is {client.raw.get('filming', {}).get('block_minutes', 90)} minutes")
    log("  Open it on a phone or tablet next to the camera. 'Prompter' gives big text.")
    return 0


# ---------------------------------------------------------------- post


def cmd_post(args: argparse.Namespace) -> int:
    from post import finish
    from transcribe import transcribe

    client = config.load_client(args.client)
    conn = store.connect()
    src = Path(args.video)
    if not src.exists():
        log(f"No such video: {src}")
        return 1

    asset = store.get_asset(conn, client.slug, args.slug)
    out_dir = Path(asset["dir_path"]) if asset else (OUT / args.slug)

    segments: list[dict[str, Any]] = []
    if not args.no_captions:
        log("  transcribing the filmed take for captions")
        try:
            from shared import llm

            tr = llm.transcribe_audio(str(src))
            segments = tr.get("segments", [])
            log(f"  {len(segments)} caption segments")
        except Exception as exc:  # noqa: BLE001
            log(f"  ! transcription failed ({str(exc)[:120]}); continuing without captions")

    result = finish(src, out_dir, slug=args.slug, segments=segments)
    log("\n  " + json.dumps(result, indent=2).replace("\n", "\n  "))
    if asset:
        store.set_asset_status(conn, asset["id"], "rendered")
    return 0


# ---------------------------------------------------------------- shared cmds


def cmd_list(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    ideas = store.list_ideas(conn, client.slug, lane="reel")
    log(f"\n== REEL IDEA QUEUE ({client.name}) ==")
    if not ideas:
        log("  (empty — run: python run.py mine)")
    for i in ideas[:40]:
        log(f"  [{i['id']:>3}] {i['status']:<10} {i['score']:>5.1f}x  "
            f"{i['source_handle'][:20]:<20} {i['title'][:46]}")

    log("\n== REEL SCRIPTS ==")
    any_asset = False
    for a in store.list_assets(conn, client.slug):
        if a["lane"] != "reel":
            continue
        any_asset = True
        log(f"  [{a['id']:>3}] {a['status']:<18} {a['slug']}")
    if not any_asset:
        log("  (none)")
    log("")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    asset = store.get_asset(conn, client.slug, args.slug)
    if asset is None:
        log(f"No asset with slug {args.slug!r}")
        return 1
    decision = "rejected" if args.reject else "approved"
    store.record_approval(conn, asset_id=asset["id"], gate="clinical",
                          approver=args.approver, decision=decision, note=args.note or "")
    store.set_asset_status(conn, asset["id"],
                           "approved" if decision == "approved" else "blocked")
    log(f"Recorded clinical {decision} by {args.approver} for {args.slug}.")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    asset = store.get_asset(conn, client.slug, args.slug)
    if asset is None:
        log(f"No asset with slug {args.slug!r}")
        return 1
    if not store.has_approval(conn, asset["id"], "clinical"):
        log("BLOCKED: no clinical approval on file. Run `approve` first.")
        return 2

    script = json.loads(asset["payload"] or "{}")
    result = compliance.check_reel_script(script, client, conn=conn)
    if not result.passed:
        log("BLOCKED: compliance re-check failed at publish time.")
        log(result.report())
        return 2

    out_dir = Path(asset["dir_path"])
    files = [str(p) for p in sorted(out_dir.glob("*.mp4"))] or \
            [str(p) for p in sorted(out_dir.glob("*.json"))]
    claims = [dict(r) for r in store.get_claims(conn, asset["id"])]
    approvals = [dict(r) for r in store.get_approvals(conn, asset["id"])]

    for platform in args.platform:
        arc = store.archive_publication(
            conn, client=client.slug, asset_id=asset["id"], slug=asset["slug"],
            lane="reel", platform=platform, caption=asset["caption"] or "",
            identification=client.identification_block, asset_paths=files,
            claims=claims, approvals=approvals,
        )
        log(f"Archived publication #{arc} -> {platform} (3-year retention)")
    store.set_asset_status(conn, asset["id"], "published")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Tailor captions per platform and write an upload-ready bundle."""
    client = config.load_client(args.client)
    conn = store.connect()
    asset = store.get_asset(conn, client.slug, args.slug)
    if asset is None:
        log(f"No asset with slug {args.slug!r}")
        return 1

    script = json.loads(asset["payload"] or "{}")
    ok, why = publish.preflight(conn=conn, client=client, asset_row=asset,
                                payload=script, lane="reel")
    if not ok and not args.skip_gate:
        log("BLOCKED at publish gate:\n  " + why.replace("\n", "\n  "))
        log("\n  (--skip-gate exports for review only. It does not clear the gate.)")
        return 2

    targets = args.platform or client.channels.get(
        "reel_publish_to", ["instagram", "facebook", "tiktok"])
    log(f"  tailoring caption for: {', '.join(targets)}")
    captions = platforms.tailor_all(script.get("caption", ""), client, targets)

    failed: list[str] = []
    for plat, data in captions.items():
        if data.get("_error"):
            log(f"    ! {plat}: {data['_error']}")
            continue
        text = data.get("caption", "")
        log(f"    -- {plat}: {len(text.split())} words, "
            f"{len(data.get('hashtags', []))} hashtags")
        res = compliance.check_text(text, client, where=f"caption:{plat}")
        if not res.passed:
            failed.append(plat)
            for f in res.blocks:
                log(f"       BLOCK {f.message}")
        for line in voice.slop_report(text).splitlines():
            if "clean" not in line:
                log("       " + line.strip())
        for prob in platforms.validate(text, plat):
            log(f"       WARN {prob}")

    if failed and not args.skip_gate:
        log(f"\n  BLOCKED: tailored caption failed compliance for {', '.join(failed)}.")
        return 2

    out_dir = Path(asset["dir_path"])
    files = [str(p) for p in sorted(out_dir.glob("*-captioned.mp4"))] or \
            [str(p) for p in sorted(out_dir.glob("*.mp4"))]
    covers = [str(p) for p in sorted(out_dir.glob("*-cover.jpg"))]
    if not files:
        log("  ! no finished video yet — run `post --video <take> --slug <slug>` first")

    publish.export_bundle(
        client=client, slug=asset["slug"], lane="reel", asset_paths=files + covers,
        captions=captions, out_root=OUT, scheduled_for=args.at or "",
    )
    bundle = OUT / "publish" / asset["slug"]
    (bundle / "captions.json").write_text(
        json.dumps(captions, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"\n  Bundle: {bundle}")
    if publish.blotato_available():
        log("  BLOTATO_API_KEY is set — scheduling via Blotato is available.")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    rows = [r for r in store.list_archive(conn, client.slug) if r["lane"] == "reel"]
    log(f"\n== REEL ADVERTISEMENT ARCHIVE ({client.name}) — {len(rows)} record(s) ==\n")
    for r in rows:
        log(f"  #{r['id']:<4} {r['published_at'][:19]}  {r['platform']:<10} {r['slug']}")
        log(f"        retain until {r['retain_until']}   sha256 {r['sha256'][:16]}…")
    log("")
    return 0


# ---------------------------------------------------------------- cli


def main() -> int:
    ap = argparse.ArgumentParser(description="Part D — Capture-First Reels Engine")
    ap.add_argument("--client", default=config.default_client())
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mine")
    m.add_argument("--multiple", type=float, default=3.0)
    m.add_argument("--limit", type=int, default=30, help="posts fetched per creator")
    m.add_argument("--max-ideas", type=int, default=25)
    m.add_argument("--csv", help="mine from a CSV export instead of the watchlist")
    m.set_defaults(fn=cmd_mine)

    s = sub.add_parser("script")
    s.add_argument("--next", action="store_true")
    s.add_argument("--all", action="store_true")
    s.add_argument("--limit", type=int, default=14)
    s.add_argument("--fixture", action="store_true")
    s.add_argument("--advisory", action="store_true")
    s.set_defaults(fn=cmd_script)

    p = sub.add_parser("packet")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--include-blocked", action="store_true")
    p.set_defaults(fn=cmd_packet)

    po = sub.add_parser("post")
    po.add_argument("--video", required=True)
    po.add_argument("--slug", required=True)
    po.add_argument("--no-captions", action="store_true")
    po.set_defaults(fn=cmd_post)

    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("archive").set_defaults(fn=cmd_archive)

    a = sub.add_parser("approve")
    a.add_argument("--slug", required=True)
    a.add_argument("--approver", required=True)
    a.add_argument("--note", default="")
    a.add_argument("--reject", action="store_true")
    a.set_defaults(fn=cmd_approve)

    e = sub.add_parser("export")
    e.add_argument("--slug", required=True)
    e.add_argument("--platform", nargs="+")
    e.add_argument("--at", default="", help="ISO time to schedule for")
    e.add_argument("--skip-gate", action="store_true")
    e.set_defaults(fn=cmd_export)

    pu = sub.add_parser("publish")
    pu.add_argument("--slug", required=True)
    pu.add_argument("--platform", nargs="+", default=["instagram"])
    pu.set_defaults(fn=cmd_publish)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

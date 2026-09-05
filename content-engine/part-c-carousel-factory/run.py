"""
Part C — Carousel Factory. Command line entry point.

    python run.py seed                          # put example topics in the queue
    python run.py list                          # show queue + assets
    python run.py build --next                  # take the top idea, build it
    python run.py build --topic "Is a root canal painful"
    python run.py build --fixture               # offline: render sample data, no API calls
    python run.py render --slug <slug>          # re-render from the saved outline
    python run.py approve --slug <slug> --approver "Dr. Example" [--reject]
    python run.py publish --slug <slug> --platform instagram
    python run.py archive                       # show the 3-year advertisement archive

Flow: research -> outline -> compliance gate -> render -> review -> clinical
approval -> publish + archive. The compliance gate is blocking: a failed check
stops the run before anything renders.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import compliance, config, console, platforms, publish, store, voice  # noqa: E402

console.init()

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FIXTURE = HERE / "fixtures" / "sample_outline.json"

SEED_TOPICS = [
    ("Is a root canal actually painful?", "Defuse the single biggest fear in dentistry", "question"),
    ("Why a deep cleaning when nothing hurts", "Gum disease is silent until it isn't", "explainer"),
    ("5 signs your gums need attention", "Give the reader something to check tonight", "checklist"),
    ("Whitening will not ruin your enamel", "Correct the most common whitening myth", "myth"),
    ("What actually counts as a dental emergency", "Help people decide whether to wait", "checklist"),
    ("Do I really need this crown?", "Address the fear of being upsold", "question"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- commands


def cmd_seed(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    added = 0
    for title, angle, _tpl in SEED_TOPICS:
        if store.add_idea(
            conn, client=client.slug, lane="carousel", title=title,
            angle=angle, source="seed", score=1.0,
        ):
            added += 1
    log(f"Seeded {added} carousel idea(s) for {client.name}.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    ideas = store.list_ideas(conn, client.slug, lane="carousel")
    assets = store.list_assets(conn, client.slug)

    log(f"\n== IDEA QUEUE ({client.name}) ==")
    if not ideas:
        log("  (empty — run: python run.py seed)")
    for i in ideas:
        log(f"  [{i['id']:>3}] {i['status']:<10} score={i['score']:<5.1f} {i['title']}")

    log("\n== ASSETS ==")
    if not assets:
        log("  (none)")
    for a in assets:
        if a["lane"] != "carousel":
            continue
        log(f"  [{a['id']:>3}] {a['status']:<18} {a['slug']}")
    log("")
    return 0


def _load_fixture() -> dict[str, Any]:
    if not FIXTURE.exists():
        raise SystemExit(f"Fixture missing: {FIXTURE}")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def cmd_build(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    run_id = store.start_run(conn, "part-c", "build", client.slug)

    idea_row = None
    try:
        # ---------------------------------------------------- 1. pick a topic
        if args.fixture:
            outline = _load_fixture()
            # The fixture ships without the live identification block so that it
            # always reflects the current client profile.
            if outline.get("slides"):
                outline["slides"][-1]["identification"] = client.identification_block
            topic = outline.get("topic", "fixture")
            angle = "offline fixture"
            log(f"\n[1/5] FIXTURE MODE — using {FIXTURE.name}, no API calls")
        else:
            if args.topic:
                topic, angle = args.topic, args.angle or ""
            else:
                idea_row = store.next_idea(conn, client.slug, "carousel")
                if idea_row is None:
                    log("Queue is empty. Run: python run.py seed")
                    store.finish_run(conn, run_id, "empty")
                    return 1
                topic, angle = idea_row["title"], idea_row["angle"] or ""
            log(f"\n[1/5] TOPIC: {topic}")

            # ------------------------------------------------ 2. research
            from research import research_topic

            log("[2/5] RESEARCH")
            research = research_topic(topic, angle, client)
            cited = sum(1 for c in research.get("claims", []) if c.get("source_url"))
            log(f"      {len(research.get('claims', []))} claims, {cited} cited, "
                f"{len(research.get('sources', []))} sources")

            # ------------------------------------------------ 3. outline
            from outline import build_outline

            log("[3/5] OUTLINE")
            outline = build_outline(topic, angle, research, client)
            log(f"      template={outline.get('template')} slides={len(outline.get('slides', []))}")

        slug = outline.get("title") or "carousel"
        slug = f"{datetime.now():%Y%m%d}-{slug}"[:80]
        out_dir = OUT / slug

        # ---------------------------------------------------- 4. compliance
        log("[4/5] COMPLIANCE GATE")
        result = compliance.check_carousel(outline, client, conn=conn)
        if args.advisory and result.passed:
            copy_blob = "\n".join(
                f"{s.get('headline','')}\n{s.get('body','')}" for s in outline.get("slides", [])
            ) + "\n" + outline.get("caption", "")
            compliance.apply_advisory(result, copy_blob, where="carousel")
        report = result.report()
        outline["_compliance_report"] = report
        for line in report.splitlines():
            log("      " + line)

        # Style lint. Warnings only — a stylistic tic must never block a
        # publish, or people start disabling the gate that also catches the
        # regulatory problems. See DECISIONS.md D-22.
        copy_all = "\n".join(
            f"{s.get('headline','')} {s.get('body','')}" for s in outline.get("slides", [])
        ) + "\n" + outline.get("caption", "")
        slop = voice.slop_report(copy_all)
        outline["_slop_report"] = slop
        for line in slop.splitlines():
            log("      " + line)

        from outline import flatten_claims  # noqa: E402
        claims = flatten_claims(outline)

        asset_id = store.create_asset(
            conn, client=client.slug, lane="carousel", slug=slug,
            idea_id=idea_row["id"] if idea_row is not None else None,
            template=outline.get("template", ""), caption=outline.get("caption", ""),
            dir_path=str(out_dir), payload=outline,
        )
        store.record_claims(conn, asset_id, claims)

        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "outline.json").write_text(
            json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        if not result.passed:
            store.set_asset_status(conn, asset_id, "blocked")
            store.record_approval(
                conn, asset_id=asset_id, gate="compliance", approver="system",
                decision="rejected", note=report[:2000],
            )
            log(f"\n  BLOCKED — {len(result.blocks)} failing check(s). Nothing rendered.")
            log(f"  Outline saved for editing: {out_dir / 'outline.json'}")
            log("  Fix the outline, then: python run.py render --slug " + slug)
            store.finish_run(conn, run_id, "blocked", report)
            return 2

        store.set_asset_status(conn, asset_id, "compliance_passed")

        # ---------------------------------------------------- 5. render
        log("[5/5] RENDER")
        from render import render_carousel

        artifacts = render_carousel(outline, client, out_dir, png=not args.no_png)
        store.set_asset_status(conn, asset_id, "rendered")

        log(f"\n  DONE  {len(artifacts['png']) or len(artifacts['html'])} slides")
        log(f"  Review: {artifacts['review']}")
        log(f"  Next:   python run.py approve --slug {slug} --approver \"{client.compliance.get('clinical_approver','Dr.')}\"")

        if idea_row is not None:
            store.set_idea_status(conn, idea_row["id"], "built")
        store.finish_run(conn, run_id, "ok", slug)
        return 0

    except Exception as exc:  # noqa: BLE001
        store.finish_run(conn, run_id, "error", str(exc))
        raise


def cmd_render(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    asset = store.get_asset(conn, client.slug, args.slug)
    if asset is None:
        log(f"No asset with slug {args.slug!r}")
        return 1
    out_dir = Path(asset["dir_path"])
    outline_path = out_dir / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))

    result = compliance.check_carousel(outline, client, conn=conn)
    outline["_compliance_report"] = result.report()
    log(result.report())
    if not result.passed and not args.force:
        log("\nStill blocked. Edit outline.json, or pass --force to render anyway "
            "(the block is still recorded).")
        return 2

    from render import render_carousel

    artifacts = render_carousel(outline, client, out_dir, png=not args.no_png)
    store.set_asset_status(conn, asset["id"], "rendered" if result.passed else "blocked")
    log(f"Review: {artifacts['review']}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    asset = store.get_asset(conn, client.slug, args.slug)
    if asset is None:
        log(f"No asset with slug {args.slug!r}")
        return 1
    decision = "rejected" if args.reject else "approved"
    store.record_approval(
        conn, asset_id=asset["id"], gate="clinical", approver=args.approver,
        decision=decision, note=args.note or "",
    )
    store.set_asset_status(conn, asset["id"], "approved" if decision == "approved" else "blocked")
    log(f"Recorded clinical {decision} by {args.approver} for {args.slug}.")
    if decision == "approved":
        log(f"Next: python run.py publish --slug {args.slug} --platform instagram")
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

    outline = json.loads(asset["payload"] or "{}")
    result = compliance.check_carousel(outline, client, conn=conn)
    if not result.passed:
        log("BLOCKED: compliance re-check failed at publish time.")
        log(result.report())
        return 2

    out_dir = Path(asset["dir_path"])
    files = sorted(str(p) for p in out_dir.glob("slide-*.png")) or \
            sorted(str(p) for p in out_dir.glob("slide-*.html"))

    claims = [dict(r) for r in store.get_claims(conn, asset["id"])]
    approvals = [dict(r) for r in store.get_approvals(conn, asset["id"])]

    for platform in args.platform:
        arc_id = store.archive_publication(
            conn, client=client.slug, asset_id=asset["id"], slug=asset["slug"],
            lane="carousel", platform=platform, caption=asset["caption"] or "",
            identification=client.identification_block, asset_paths=files,
            claims=claims, approvals=approvals,
        )
        log(f"Archived publication #{arc_id} -> {platform} "
            f"(retention 3 years, {len(files)} files hashed)")

    store.set_asset_status(conn, asset["id"], "published")
    log("\nNOTE: this records the publication for the N.J.A.C. 13:30-6.2 archive. "
        "Uploading to the platform is a separate step — see README 'Publishing'.")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Tailor captions per platform and write an upload-ready bundle."""
    client = config.load_client(args.client)
    conn = store.connect()
    asset = store.get_asset(conn, client.slug, args.slug)
    if asset is None:
        log(f"No asset with slug {args.slug!r}")
        return 1

    outline = json.loads(asset["payload"] or "{}")
    ok, why = publish.preflight(conn=conn, client=client, asset_row=asset,
                                payload=outline, lane="carousel")
    if not ok and not args.skip_gate:
        log("BLOCKED at publish gate:\n  " + why.replace("\n", "\n  "))
        log("\n  (--skip-gate exports anyway, for review only. "
            "It does not clear the gate.)")
        return 2

    targets = args.platform or client.channels.get("publish_to", ["instagram"])
    log(f"  tailoring caption for: {', '.join(targets)}")
    captions = platforms.tailor_all(outline.get("caption", ""), client, targets)
    failed: list[str] = []
    for plat, data in captions.items():
        if data.get("_error"):
            log(f"    ! {plat}: {data['_error']}")
            continue
        text = data.get("caption", "")
        words = len(text.split())
        log(f"    -- {plat}: {words} words, {len(data.get('hashtags', []))} hashtags")

        # The tailored caption is NEW copy the model just wrote, so it has to
        # clear the same gate the outline did. Skipping this was a real bug:
        # a compliant carousel produced a non-compliant Instagram caption.
        # See DECISIONS.md D-23.
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
        log("  Nothing was exported. Re-run to regenerate, or fix the source caption.")
        return 2

    out_dir = Path(asset["dir_path"])
    files = sorted(str(p) for p in out_dir.glob("slide-*.png")) or \
            sorted(str(p) for p in out_dir.glob("slide-*.html"))
    publish.export_bundle(
        client=client, slug=asset["slug"], lane="carousel", asset_paths=files,
        captions=captions, out_root=OUT, scheduled_for=args.at or "",
    )
    bundle = OUT / "publish" / asset["slug"]
    (bundle / "captions.json").write_text(
        json.dumps(captions, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"\n  Bundle: {bundle}")
    log("  Upload the numbered media in order, paste the matching caption file.")
    if publish.blotato_available():
        log("  BLOTATO_API_KEY is set — scheduling via Blotato is available.")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    rows = store.list_archive(conn, client.slug)
    log(f"\n== ADVERTISEMENT ARCHIVE ({client.name}) — {len(rows)} record(s) ==")
    log("Retention: 3 years from publication. This table is append-only.\n")
    for r in rows:
        log(f"  #{r['id']:<4} {r['published_at'][:19]}  {r['platform']:<10} "
            f"{r['lane']:<9} {r['slug']}")
        log(f"        retain until {r['retain_until']}   sha256 {r['sha256'][:16]}…")
    log("")
    return 0


# ---------------------------------------------------------------- cli


def main() -> int:
    ap = argparse.ArgumentParser(description="Part C — Carousel Factory")
    ap.add_argument("--client", default=config.default_client())
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("archive").set_defaults(fn=cmd_archive)

    b = sub.add_parser("build")
    b.add_argument("--topic")
    b.add_argument("--angle", default="")
    b.add_argument("--next", action="store_true", help="take the top queued idea")
    b.add_argument("--fixture", action="store_true", help="offline render, no API calls")
    b.add_argument("--no-png", action="store_true", help="write HTML only, skip Chrome")
    b.add_argument("--advisory", action="store_true", help="add the LLM dignity review")
    b.set_defaults(fn=cmd_build)

    r = sub.add_parser("render")
    r.add_argument("--slug", required=True)
    r.add_argument("--no-png", action="store_true")
    r.add_argument("--force", action="store_true")
    r.set_defaults(fn=cmd_render)

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

    p = sub.add_parser("publish")
    p.add_argument("--slug", required=True)
    p.add_argument("--platform", nargs="+", default=["instagram"])
    p.set_defaults(fn=cmd_publish)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

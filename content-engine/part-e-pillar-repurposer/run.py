"""
Part E — Pillar Repurposer. Command line entry point.

This is reference video 1's pipeline, built end to end with the paid pieces
swapped out:

    transcript -> concept -> voice lint -> photo pick -> cover
               -> plates -> render -> self-check -> review -> schedule

    their FAL      -> real photo + CSS treatment in headless Chrome   (free)
    their Blotato  -> export bundle, with an optional Blotato adapter (free)

    python run.py photos scan                      # index your photo library
    python run.py build --from <youtube-url>       # the whole pipeline
    python run.py build --from talk.txt
    python run.py build --fixture                  # offline, no API calls
    python run.py list
    python run.py approve --slug <slug> --approver "Dr. Example"
    python run.py export  --slug <slug> --platform instagram facebook
    python run.py publish --slug <slug> --platform instagram
    python run.py archive
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
FIXTURE = HERE / "fixtures" / "sample_pillar.txt"


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- photos


def cmd_photos(args: argparse.Namespace) -> int:
    import assets

    if args.action == "scan":
        result = assets.scan()
        log(f"Scanned {assets.PHOTO_DIR}")
        log(f"  {result['added']} new, {result['total']} total")
        log(f"  Manifest: {result['path']}")
        if result["total"] == 0:
            log("\n  Drop real photos of the practice into assets/photos/ and "
                "re-run.\n  Then fill in 'description' for each one — that is what "
                "the picker reads.")
        else:
            missing = [p["id"] for p in assets.load_manifest()
                       if not (p.get("description") or "").strip()]
            if missing:
                log(f"  {len(missing)} photo(s) still need a description: "
                    f"{', '.join(missing[:6])}{'…' if len(missing) > 6 else ''}")
        return 0

    for p in assets.load_manifest():
        flag = ""
        if p.get("depicts_patient"):
            flag = f"  [patient: consent {p.get('consent','missing')}]"
        log(f"  {p['id']:<28} {p.get('orientation',''):<10} "
            f"{(p.get('description') or '(no description)')[:52]}{flag}")
    return 0


# ---------------------------------------------------------------- build


def cmd_build(args: argparse.Namespace) -> int:
    import assets
    import cover as cover_mod
    import pillar
    import review as review_mod

    client = config.load_client(args.client)
    conn = store.connect()
    run_id = store.start_run(conn, "part-e", "build", client.slug)

    try:
        # ------------------------------------------------ 1. transcript
        source = args.source or (str(FIXTURE) if args.fixture else "")
        if not source:
            log("Give me something to repurpose: --from <url|file> or --fixture")
            store.finish_run(conn, run_id, "empty")
            return 1

        log(f"\n[1/9] PILLAR  {source}")
        try:
            pillar.assert_ownership(source, confirmed=args.own_content)
        except pillar.OwnershipError as exc:
            log("\n  " + str(exc).replace("\n", "\n  "))
            store.finish_run(conn, run_id, "refused", "ownership not confirmed")
            return 3
        loaded = pillar.load_pillar(source)
        words = len(loaded["text"].split())
        log(f"      {words:,} words via {loaded['source']}")
        if words < 120:
            log("      ! that is very short; the concept will be thin")

        # ------------------------------------------------ 2. concept
        log("[2/9] CONCEPT")
        concept = pillar.build_concept(loaded["text"], client)
        outline = pillar.to_outline(concept, client)
        outline["_pillar"]["origin"] = loaded["origin"]
        log(f"      \"{concept.get('angle','')[:76]}\"")
        log(f"      {len(outline['slides'])} slides "
            f"(cover + {len(concept.get('slides', []))} body + cta)")

        slug = f"{datetime.now():%Y%m%d}-{outline['title']}"[:80]
        out_dir = OUT / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------ 3. voice lint
        log("[3/9] VOICE LINT")
        copy_all = "\n".join(
            f"{s.get('headline','')} {s.get('body','')}" for s in outline["slides"]
        ) + "\n" + outline.get("caption", "")
        slop = voice.slop_report(copy_all)
        outline["_slop_report"] = slop
        for line in slop.splitlines():
            log("      " + line)

        # ------------------------------------------------ 4. compliance
        log("[4/9] COMPLIANCE GATE")
        result = compliance.check_carousel(outline, client, conn=conn)
        for line in result.report().splitlines():
            log("      " + line)

        # One repair pass. The gate stays authoritative — the revision has to
        # pass it on its own, and a second failure blocks like any other.
        if not result.passed and args.fix:
            log(f"      --fix: asking for a revision of {len(result.blocks)} block(s)")
            try:
                outline = pillar.revise_outline(outline, result.report(), client)
                result = compliance.check_carousel(outline, client, conn=conn)
                log("      after revision:")
                for line in result.report().splitlines():
                    log("        " + line)
            except Exception as exc:  # noqa: BLE001
                log(f"      ! revision failed ({str(exc)[:110]})")

        outline["_compliance_report"] = result.report()

        claims = [
            {**c, "slide_no": i}
            for i, s in enumerate(outline["slides"], start=1)
            for c in (s.get("claims") or [])
        ]
        asset_id = store.create_asset(
            conn, client=client.slug, lane="carousel", slug=slug,
            template="pillar", caption=outline.get("caption", ""),
            dir_path=str(out_dir), payload=outline,
        )
        store.record_claims(conn, asset_id, claims)
        (out_dir / "outline.json").write_text(
            json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8")

        if not result.passed:
            store.set_asset_status(conn, asset_id, "blocked")
            store.record_approval(conn, asset_id=asset_id, gate="compliance",
                                  approver="system", decision="rejected",
                                  note=result.report()[:2000])
            log(f"\n  BLOCKED — {len(result.blocks)} failing check(s). Nothing rendered.")
            log(f"  Outline saved: {out_dir / 'outline.json'}")
            log("  Either re-run with --fix to have it repaired automatically,")
            log(f"  or edit that file and run: python run.py render --slug {slug}")
            store.finish_run(conn, run_id, "blocked")
            return 2
        store.set_asset_status(conn, asset_id, "compliance_passed")

        final, plate_pngs = render_all(outline, client, out_dir,
                                       no_png=args.no_png, log=log)
        store.set_asset_status(conn, asset_id, "rendered")

        log(f"\n  DONE  {len(final) or len(plate_pngs)} slides")
        log(f"  Review: {out_dir / 'review.html'}")
        log(f"  Next:   python run.py approve --slug {slug} "
            f"--approver \"{client.compliance.get('clinical_approver','Dr.')}\"")
        store.finish_run(conn, run_id, "ok", slug)
        return 0

    except Exception as exc:  # noqa: BLE001
        store.finish_run(conn, run_id, "error", str(exc))
        raise


def render_all(
    outline: dict[str, Any],
    client: Any,
    out_dir: Path,
    *,
    no_png: bool = False,
    log=log,
) -> tuple[list[Path], list[Path]]:
    """Stages 5-9: photo pick, covers, self-check, review, plates, assemble.

    Shared by `build` and `render` so a hand-edited outline goes through exactly
    the same path as a freshly generated one.
    """
    import assets
    import cover as cover_mod
    import review as review_mod

    cover = {
        "headline": outline["slides"][0].get("headline", ""),
        "subtext": outline["slides"][0].get("body", ""),
    }

    # ---------------------------------------------------------- 5. photo pick
    log("[5/9] PHOTO PICK")
    library = assets.usable(assets.load_manifest())
    if not library:
        log("      ! no usable photos in the library.")
        log("        Drop photos into assets/photos/, run `photos scan`, and add")
        log("        descriptions. Rendering plates only for now.")
        photo_choice = None
    else:
        photo_choice = assets.pick_photo(
            cover, outline.get("_pillar", {}).get("photo_brief", ""))
        log(f"      {photo_choice['photo']['id']} — {photo_choice['why'][:70]}")
        log(f"      text {photo_choice['text_position']}, "
            f"{photo_choice['scrim']} scrim")

    # ------------------------------------------------------ 6. cover variants
    for f in review_mod.check_text_fit(cover["headline"], cover["subtext"]):
        log(f"      WARN {f}")

    cover_pngs: list[dict[str, Any]] = []
    if photo_choice:
        log("[6/9] COVER VARIANTS")
        cover_pngs = cover_mod.render_variants(
            outline, client, photo_choice, out_dir, png=not no_png, log=log)
    else:
        log("[6/9] COVER VARIANTS — skipped, no photo")

    # ---------------------------------------------------------- 7. self-check
    winner_png: Path | None = None
    if cover_pngs and not no_png:
        log("[7/9] SELF-CHECK (mechanical)")
        clean: list[dict[str, Any]] = []
        for v in cover_pngs:
            probs = review_mod.self_check(
                Path(v["png"]), position=v["position"], scrim=v["scrim"])
            if probs:
                for p in probs:
                    log(f"      FAIL {p}")
            else:
                log(f"      ok   {v['name']}")
                clean.append(v)
        if not clean:
            log("      ! every variant failed the mechanical check; using the "
                "first anyway so you can look at it")
            clean = cover_pngs

        # ------------------------------------------------------- 8. review
        log("[8/9] REVIEW (taste)")
        verdict = review_mod.pick_cover(clean, log=log)
        log(f"      winner: {verdict.get('winner')} — {verdict.get('why','')[:80]}")
        if verdict.get("fix"):
            log(f"      suggested fix: {verdict['fix'][:90]}")
        outline["_cover_review"] = verdict
        chosen = next((v for v in clean if v["name"] == verdict.get("winner")), clean[0])
        winner_png = Path(chosen["png"])
    else:
        log("[7/9] SELF-CHECK — skipped\n[8/9] REVIEW — skipped")

    # ------------------------------------------------- 9. plates + assemble
    log("[9/9] PLATES")
    _, plate_pngs = cover_mod.render_plates(
        outline, client, out_dir, png=not no_png, log=log)

    final: list[Path] = []
    if winner_png and plate_pngs:
        final = cover_mod.assemble(winner_png, plate_pngs, out_dir, log=log)

    (out_dir / "outline.json").write_text(
        json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8")
    write_review_page(outline, client, out_dir, cover_pngs, final)
    return final, plate_pngs


def cmd_render(args: argparse.Namespace) -> int:
    """Re-render from a hand-edited outline.json."""
    client = config.load_client(args.client)
    conn = store.connect()
    asset = store.get_asset(conn, client.slug, args.slug)
    if asset is None:
        log(f"No asset with slug {args.slug!r}")
        return 1

    out_dir = Path(asset["dir_path"])
    outline = json.loads((out_dir / "outline.json").read_text(encoding="utf-8"))

    result = compliance.check_carousel(outline, client, conn=conn)
    outline["_compliance_report"] = result.report()
    for line in result.report().splitlines():
        log("  " + line)
    if not result.passed and not args.force:
        log("\nStill blocked. Fix outline.json, or pass --force to render anyway "
            "(the block stays recorded and publishing is still refused).")
        return 2

    final, plate_pngs = render_all(outline, client, out_dir,
                                   no_png=args.no_png, log=log)
    store.create_asset(
        conn, client=client.slug, lane="carousel", slug=args.slug,
        template="pillar", caption=outline.get("caption", ""),
        dir_path=str(out_dir), payload=outline)
    store.set_asset_status(conn, asset["id"],
                           "rendered" if result.passed else "blocked")
    log(f"\n  DONE  {len(final) or len(plate_pngs)} slides")
    log(f"  Review: {out_dir / 'review.html'}")
    return 0


def write_review_page(
    outline: dict[str, Any],
    client: Any,
    out_dir: Path,
    variants: list[dict[str, Any]],
    final: list[Path],
) -> Path:
    import html as h

    def figs(paths: list[str], labels: list[str]) -> str:
        out = []
        for p, lab in zip(paths, labels):
            out.append(f'<figure><img src="{h.escape(Path(p).name)}" alt="">'
                       f'<figcaption>{h.escape(lab)}</figcaption></figure>')
        return "\n".join(out)

    verdict = outline.get("_cover_review", {})
    var_names = [v["name"] + (" ← winner" if v["name"] == verdict.get("winner") else "")
                 for v in variants]
    var_paths = [v.get("png") or v["html"] for v in variants]

    final_rel = [str(Path("final") / p.name) for p in final]
    final_labels = [p.name for p in final]

    doc = f"""<!doctype html><meta charset="utf-8">
<title>Review — {h.escape(outline.get('title',''))}</title>
<style>
 body{{font:15px/1.6 ui-sans-serif,system-ui,sans-serif;margin:0;
   background:#10171d;color:#e4ebef}}
 .wrap{{max-width:1200px;margin:0 auto;padding:32px 24px 80px}}
 h1{{font-size:25px;margin:0 0 4px}}
 h2{{font-size:14px;text-transform:uppercase;letter-spacing:.1em;color:#9aabb6;
   margin:30px 0 12px}}
 .meta{{color:#9aabb6;font-size:13px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}}
 figure{{margin:0;background:#161f26;border:1px solid #25323b;border-radius:6px;
   overflow:hidden}}
 img{{width:100%;display:block;aspect-ratio:4/5;object-fit:cover}}
 figcaption{{padding:8px 10px;font-size:12px;color:#9aabb6;
   font-family:ui-monospace,monospace}}
 .panel{{background:#161f26;border:1px solid #25323b;border-radius:6px;
   padding:16px 18px;margin-bottom:16px}}
 pre{{white-space:pre-wrap;font-size:12.5px;margin:0}}
 .block{{color:#dd8878}} .warn{{color:#e3b778}} .ok{{color:#77b792}}
</style>
<div class="wrap">
<h1>{h.escape(outline.get('topic') or outline.get('title',''))}</h1>
<div class="meta">pillar repurpose &middot; {len(outline.get('slides',[]))} slides
  &middot; {h.escape(client.name)}</div>

<div class="panel"><h2 style="margin-top:0">Compliance</h2>
<pre class="{'block' if 'BLOCK' in outline.get('_compliance_report','') else 'ok'}">{h.escape(outline.get('_compliance_report','(not run)'))}</pre></div>

<div class="panel"><h2 style="margin-top:0">Slop lint</h2>
<pre class="{'warn' if 'clean' not in outline.get('_slop_report','') else 'ok'}">{h.escape(outline.get('_slop_report','(not run)'))}</pre></div>

<div class="panel"><h2 style="margin-top:0">Cover review</h2>
<pre>winner: {h.escape(str(verdict.get('winner','-')))}
why: {h.escape(str(verdict.get('why','-')))}
fix: {h.escape(str(verdict.get('fix','-')))}</pre></div>

<div class="panel"><h2 style="margin-top:0">Source</h2>
<pre>{h.escape(outline.get('_pillar',{}).get('origin',''))}

{h.escape(outline.get('_pillar',{}).get('summary',''))}</pre></div>

<div class="panel"><h2 style="margin-top:0">Caption</h2>
<pre>{h.escape(outline.get('caption',''))}</pre>
<p style="color:#9aabb6;font-size:12.5px">{h.escape(' '.join(outline.get('hashtags',[])))}</p></div>

<h2>Cover variants</h2><div class="grid">{figs(var_paths, var_names)}</div>
<h2>Final carousel</h2><div class="grid">{figs(final_rel, final_labels)}</div>
</div>"""
    p = out_dir / "review.html"
    p.write_text(doc, encoding="utf-8")
    return p


# ---------------------------------------------------------------- shared cmds


def cmd_list(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    rows = [a for a in store.list_assets(conn, client.slug)
            if (json.loads(a["payload"] or "{}").get("template") == "pillar")]
    log(f"\n== PILLAR CAROUSELS ({client.name}) ==")
    if not rows:
        log("  (none — run: python run.py build --fixture)")
    for a in rows:
        log(f"  [{a['id']:>3}] {a['status']:<18} {a['slug']}")
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
    if decision == "approved":
        log(f"Next: python run.py export --slug {args.slug}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
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

    if failed and not args.skip_gate:
        log(f"\n  BLOCKED: tailored caption failed compliance for {', '.join(failed)}.")
        return 2

    out_dir = Path(asset["dir_path"])
    final = sorted(str(p) for p in (out_dir / "final").glob("slide-*.png"))
    files = final or sorted(str(p) for p in out_dir.glob("plate-*.png"))
    publish.export_bundle(
        client=client, slug=asset["slug"], lane="carousel", asset_paths=files,
        captions=captions, out_root=OUT, scheduled_for=args.at or "")
    bundle = OUT / "publish" / asset["slug"]
    (bundle / "captions.json").write_text(
        json.dumps(captions, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"\n  Bundle: {bundle}  ({len(files)} slides)")
    if publish.blotato_available():
        log("  BLOTATO_API_KEY is set — scheduling via Blotato is available.")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    asset = store.get_asset(conn, client.slug, args.slug)
    if asset is None:
        log(f"No asset with slug {args.slug!r}")
        return 1
    outline = json.loads(asset["payload"] or "{}")
    ok, why = publish.preflight(conn=conn, client=client, asset_row=asset,
                                payload=outline, lane="carousel")
    if not ok:
        log("BLOCKED:\n  " + why.replace("\n", "\n  "))
        return 2

    out_dir = Path(asset["dir_path"])
    files = sorted(str(p) for p in (out_dir / "final").glob("slide-*.png"))
    claims = [dict(r) for r in store.get_claims(conn, asset["id"])]
    approvals = [dict(r) for r in store.get_approvals(conn, asset["id"])]
    for platform in args.platform:
        arc = store.archive_publication(
            conn, client=client.slug, asset_id=asset["id"], slug=asset["slug"],
            lane="carousel", platform=platform, caption=asset["caption"] or "",
            identification=client.identification_block, asset_paths=files,
            claims=claims, approvals=approvals)
        log(f"Archived publication #{arc} -> {platform} (3-year retention)")
    store.set_asset_status(conn, asset["id"], "published")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    client = config.load_client(args.client)
    conn = store.connect()
    rows = store.list_archive(conn, client.slug)
    log(f"\n== ADVERTISEMENT ARCHIVE ({client.name}) — {len(rows)} record(s) ==\n")
    for r in rows:
        log(f"  #{r['id']:<4} {r['published_at'][:19]}  {r['platform']:<10} {r['slug']}")
    log("")
    return 0


# ---------------------------------------------------------------- cli


def main() -> int:
    ap = argparse.ArgumentParser(description="Part E — Pillar Repurposer")
    ap.add_argument("--client", default=config.default_client())
    sub = ap.add_subparsers(dest="cmd", required=True)

    ph = sub.add_parser("photos")
    ph.add_argument("action", choices=["scan", "list"], nargs="?", default="list")
    ph.set_defaults(fn=cmd_photos)

    b = sub.add_parser("build")
    b.add_argument("--from", dest="source", help="YouTube URL, .txt/.md, or media file")
    b.add_argument("--fixture", action="store_true", help="offline sample pillar")
    b.add_argument("--no-png", action="store_true")
    b.add_argument("--own-content", action="store_true",
                   help="confirm the source is the CLIENT'S OWN material. "
                        "Required for any http/https source.")
    b.add_argument("--fix", action="store_true",
                   help="on a compliance block, ask for one revision and re-gate")
    b.set_defaults(fn=cmd_build)

    r = sub.add_parser("render")
    r.add_argument("--slug", required=True)
    r.add_argument("--no-png", action="store_true")
    r.add_argument("--force", action="store_true")
    r.set_defaults(fn=cmd_render)

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
    e.add_argument("--at", default="")
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

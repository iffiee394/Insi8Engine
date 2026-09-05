"""
Compliance gates for regulated (dental) social content.

Two layers, deliberately in this order (DECISIONS.md D-06):

  1. DETERMINISTIC  - phrase lists, structural requirements, consent lookups.
                      Free, instant, reproducible, and testable. Runs always.
  2. ADVISORY (LLM) - "dignified manner" judgement and claim-shape review.
                      Costs a call, is non-deterministic, so it WARNS but never
                      silently passes something the deterministic layer blocked.

Grounded in N.J.A.C. 13:30-6.2 (New Jersey Board of Dentistry, professional
advertising) and HIPAA requirements for patient imagery. This encodes a reading
of those rules for pipeline purposes; it is not legal advice, and the open
question about whether each individual post is an "advertisement" is logged in
DECISIONS.md D-13.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from . import store
from .config import ClientProfile

# --------------------------------------------------------------- rule tables

# Superiority / guarantee / competence language. 13:30-6.2 bars claims of
# superiority and testimonials as to technical competence, and bars any claim
# that is false, misleading or deceptive.
DEFAULT_BANNED_PHRASES = [
    "best dentist", "best dental", "#1", "number one", "no. 1",
    "top rated", "top-rated", "highest rated", "world class", "world-class",
    "the finest", "unmatched", "unrivaled", "unrivalled", "superior to",
    "better than any", "leading expert", "foremost",
    "painless", "pain free", "pain-free", "no pain",
    "guaranteed", "guarantee", "risk free", "risk-free",
    "permanent results", "lasts forever", "never need",
    "miracle", "instant cure", "cure for",
    "100%", "always works", "everyone gets",
    "board certified" ,  # only lawful with the actual recognized specialty board
]

# Promises about how treatment will FEEL. Caught separately from the phrase list
# because models reach for these constantly when writing reassuring copy, and
# they are outcome guarantees in everything but wording. Individual experience
# varies and cannot be promised. See DECISIONS.md D-23.
COMFORT_PROMISE = [
    r"\byou (?:won'?t|will not|shouldn'?t) (?:feel|hurt|experience)\b",
    r"\b(?:it|this|the procedure|the appointment) (?:won'?t|will not) hurt\b",
    r"\bno (?:sharp )?pain\b",
    r"\b(?:completely|totally|entirely|perfectly) (?:comfortable|painless|safe|relaxed)\b",
    r"\byou'?ll feel nothing\b",
    r"\bfeel no (?:pain|discomfort)\b",
    r"\bwithout any (?:pain|discomfort)\b",
    r"\byou (?:will|'ll) be (?:comfortable|fine|okay)\b",
]

# Formats that lean on absurdity or attention techniques unrelated to selecting
# a dentist. 13:30-6.2 requires a "dignified manner".
DEFAULT_BANNED_FORMATS = [
    "trend dance", "lip sync skit", "prank", "shock hook", "meme skit",
    "thirst trap", "clickbait bodycount", "fake emergency", "jump scare",
    "gross-out", "rage bait",
]

# Words implying specialty status a general dentist may not claim.
SPECIALTY_WORDS = ["specialist", "specializes in", "specialising", "specializing in", "specialty in"]

# Language that reads as a technical-competence testimonial.
COMPETENCE_TESTIMONIAL = [
    r"\bbest (?:dentist|doctor|dds|dmd)\b",
    r"\bmost skilled\b",
    r"\bmost experienced\b",
    r"\bbetter (?:dentist|work) than\b",
    r"\bhands down the\b",
]

PRICING_TRIGGERS = [
    r"\$\s?\d", r"\b\d+\s?% off\b", r"\bdiscount\b", r"\bspecial offer\b",
    r"\bfree (?:consult|consultation|exam|whitening|cleaning)\b", r"\bstarting at\b",
    r"\bas low as\b", r"\bfinancing\b", r"\bpayment plan\b",
    # Insurance and out-of-pocket copy is fee advertising by another name: it
    # tells the reader what they will pay. Found in a real run, where a slide
    # said "many dental insurances cover root canals" and sailed through.
    r"\binsurances?\b[^.!?]{0,30}?\b(?:covers?|will cover|helps?|pays?)\b",
    r"\bcover(?:s|ed|age) (?:by|under) (?:your )?insurance\b",
    r"\bout[- ]of[- ]pocket\b", r"\bco-?pay\b", r"\bdeductible\b",
    r"\bwe accept .{0,24}insurance\b", r"\bin[- ]network\b",
    r"\baffordab(?:le|ility)\b", r"\bcheaper than\b", r"\bcosts? (?:less|more) than\b",
]


@dataclass
class Finding:
    rule: str
    severity: str          # 'block' | 'warn'
    message: str
    where: str = ""
    citation: str = ""


@dataclass
class ComplianceResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocks(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "block"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    @property
    def passed(self) -> bool:
        return not self.blocks

    def add(self, rule: str, severity: str, message: str, where: str = "", citation: str = "") -> None:
        self.findings.append(Finding(rule, severity, message, where, citation))

    def report(self) -> str:
        if not self.findings:
            return "COMPLIANCE: clean (no findings)"
        lines = [f"COMPLIANCE: {len(self.blocks)} blocking, {len(self.warnings)} warnings"]
        for f in self.findings:
            tag = "BLOCK" if f.severity == "block" else " WARN"
            loc = f" [{f.where}]" if f.where else ""
            cite = f"  ({f.citation})" if f.citation else ""
            lines.append(f"  {tag}{loc} {f.rule}: {f.message}{cite}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "findings": [
                {"rule": f.rule, "severity": f.severity, "message": f.message,
                 "where": f.where, "citation": f.citation}
                for f in self.findings
            ],
        }


# --------------------------------------------------------------- text checks


def _phrases_for(client: ClientProfile) -> list[str]:
    custom = client.banned_phrases
    return sorted(set(DEFAULT_BANNED_PHRASES + custom))


def check_text(
    text: str,
    client: ClientProfile,
    *,
    where: str = "",
    result: ComplianceResult | None = None,
) -> ComplianceResult:
    """Deterministic phrase and claim-shape checks over one block of copy."""
    res = result or ComplianceResult()
    if not text:
        return res
    low = text.lower()

    for phrase in _phrases_for(client):
        if phrase in low:
            res.add(
                "banned_phrase",
                "block",
                f"contains prohibited claim language: {phrase!r}",
                where,
                "N.J.A.C. 13:30-6.2 - no superiority or misleading claims",
            )

    designation = (client.identification.get("designation") or "").lower()
    if "general dentist" in designation:
        for w in SPECIALTY_WORDS:
            if w in low:
                res.add(
                    "specialty_implication",
                    "block",
                    f"{w!r} implies specialty status; practice is designated a general dentist",
                    where,
                    "N.J.A.C. 13:30-6.2 - specialty designation",
                )

    for pat in COMFORT_PROMISE:
        m = re.search(pat, low)
        if m:
            res.add(
                "comfort_promise",
                "block",
                f"promises how treatment will feel: {m.group(0)!r}. "
                f"Individual experience varies and cannot be guaranteed.",
                where,
                "N.J.A.C. 13:30-6.2 - no misleading or unsupportable claims",
            )

    for pat in COMPETENCE_TESTIMONIAL:
        if re.search(pat, low):
            res.add(
                "competence_testimonial",
                "block",
                f"reads as a testimonial to technical competence (matched /{pat}/)",
                where,
                "N.J.A.C. 13:30-6.2 - no testimonials as to technical competence",
            )
    return res


def mentions_pricing(text: str) -> bool:
    low = (text or "").lower()
    return any(re.search(p, low) for p in PRICING_TRIGGERS)


# --------------------------------------------------------------- asset checks


def check_carousel(
    outline: dict[str, Any],
    client: ClientProfile,
    *,
    conn: sqlite3.Connection | None = None,
) -> ComplianceResult:
    """Full gate for a carousel outline before it is allowed to render."""
    res = ComplianceResult()
    slides = outline.get("slides", []) or []

    # 1. copy checks across every slide plus the caption
    for i, slide in enumerate(slides, start=1):
        for fieldname in ("headline", "body", "kicker"):
            check_text(slide.get(fieldname, ""), client, where=f"slide {i}.{fieldname}", result=res)
    check_text(outline.get("caption", ""), client, where="caption", result=res)

    # 2. Claims. Two kinds, and only one needs an external citation:
    #
    #   clinical_general  a statement about dentistry as a field ("root canal
    #                     treatment removes infected pulp"). Needs a source URL,
    #                     because it is checkable against the literature and the
    #                     practice does not get to assert it on its own authority.
    #
    #   practice_fact     a statement about how THIS practice operates ("we hold
    #                     emergency slots every weekday morning"). There is no
    #                     external source for it and demanding one is nonsense.
    #                     It is covered by the clinical sign-off gate instead,
    #                     which is the dentist attesting it is true.
    #
    # Part C produces mostly the first kind; Part E, working from the practice's
    # own recorded words, produces mostly the second. See DECISIONS.md D-30.
    for i, slide in enumerate(slides, start=1):
        for claim in slide.get("claims", []) or []:
            source_type = (claim.get("source_type") or "").strip().lower()
            if source_type == "practice_fact":
                continue
            if claim.get("is_clinical", True) and not (claim.get("source_url") or "").strip():
                res.add(
                    "uncited_clinical_claim",
                    "block",
                    f"general clinical claim has no source: {claim.get('text','')[:90]!r}. "
                    f"Cite it, cut it, or mark it source_type='practice_fact' if it is "
                    f"a statement about this practice rather than about dentistry.",
                    f"slide {i}",
                    "N.J.A.C. 13:30-6.2 - no false or misleading statements",
                )

    # 3. identification block on the end slide
    if client.compliance.get("identification_required", True):
        tail = " ".join(
            f"{s.get('headline','')} {s.get('body','')} {s.get('identification','')}"
            for s in slides[-2:]
        ).lower()
        phone = (client.identification.get("phone") or "").strip()
        digits = re.sub(r"\D", "", phone)
        has_phone = bool(digits) and re.sub(r"\D", "", tail).find(digits) != -1
        has_name = (client.identification.get("practice_name", "").lower() or "\0") in tail
        if not (has_phone and has_name):
            res.add(
                "identification_block",
                "block",
                "final slides must carry practice name, address, phone and designation",
                "end slide",
                "N.J.A.C. 13:30-6.2 - advertisement identification",
            )

    # 4. pricing routed to a separate approval path
    all_copy = " ".join(
        f"{s.get('headline','')} {s.get('body','')}" for s in slides
    ) + " " + outline.get("caption", "")
    if mentions_pricing(all_copy):
        res.add(
            "pricing_content",
            "block",
            "mentions fees, discounts or offers; route to the pricing approval path "
            "(baseline fee from the preceding 60 days must be disclosed)",
            "copy",
            "N.J.A.C. 13:30-6.2 - fee and discount advertising",
        )

    # 5. patient imagery consent
    res = check_media_consent(outline.get("media", []) or [], client, conn=conn, result=res)

    # 6. the myth template strikes its headline through, which INVERTS meaning.
    # Applied to a true statement it publishes the opposite of the truth, which
    # is a misleading-statement problem, not a design one. Found by testing.
    if outline.get("template") == "myth":
        res.add(
            "myth_template_review",
            "warn",
            "the 'myth' template renders each headline struck through. Confirm every "
            "struck headline is genuinely a misconception the practice is correcting "
            "— a struck TRUE statement publishes the opposite of what you mean.",
            "template",
            "N.J.A.C. 13:30-6.2 - no misleading statements",
        )

    # 7. slide count sanity (Instagram hard limit is 20)
    if len(slides) > 20:
        res.add("slide_count", "block", f"{len(slides)} slides exceeds Instagram's limit of 20", "outline")
    if len(slides) < 3:
        res.add("slide_count", "warn", f"only {len(slides)} slides; carousels earn saves with depth", "outline")

    return res


def check_media_consent(
    media: list[dict[str, Any]],
    client: ClientProfile,
    *,
    conn: sqlite3.Connection | None = None,
    result: ComplianceResult | None = None,
) -> ComplianceResult:
    """Hard-block any asset depicting a patient without a matching signed release."""
    res = result or ComplianceResult()
    for m in media:
        if not m.get("depicts_patient"):
            continue
        subject = (m.get("subject_ref") or "").strip()
        if not subject:
            res.add(
                "consent_missing_ref",
                "block",
                "media marked as depicting a patient but carries no subject_ref",
                m.get("path", "media"),
                "HIPAA - full-face images are PHI",
            )
            continue
        if conn is None:
            res.add(
                "consent_unverified",
                "block",
                f"cannot verify release for {subject!r} (no database connection)",
                m.get("path", "media"),
                "HIPAA - written authorization required",
            )
            continue
        seen: set[str] = set()
        for channel in client.channels.get("publish_to", ["instagram"]):
            ok, why = store.consent_ok(conn, client.slug, subject, channel)
            if not ok and why not in seen:
                seen.add(why)
                res.add(
                    "consent_gate",
                    "block",
                    why,
                    m.get("path", "media"),
                    "HIPAA - written authorization naming the channel",
                )
    return res


def check_reel_script(
    script: dict[str, Any],
    client: ClientProfile,
    *,
    conn: sqlite3.Connection | None = None,
) -> ComplianceResult:
    """Gate for a reel script before it reaches the filming-day packet."""
    res = ComplianceResult()

    check_text(script.get("hook", ""), client, where="hook", result=res)
    for i, line in enumerate(script.get("lines", []) or [], start=1):
        check_text(line if isinstance(line, str) else line.get("text", ""), client,
                   where=f"line {i}", result=res)
    check_text(script.get("cta", ""), client, where="cta", result=res)
    check_text(script.get("caption", ""), client, where="caption", result=res)

    # format / dignity check against the blacklist
    fmt = (script.get("format") or "").lower()
    banned = [f.lower() for f in (client.banned_formats or DEFAULT_BANNED_FORMATS)]
    for b in banned:
        if b in fmt:
            res.add(
                "undignified_format",
                "block",
                f"format {fmt!r} matches banned format {b!r}",
                "format",
                "N.J.A.C. 13:30-6.2 - dignified manner",
            )

    # clinical claims in a reel still need a source on file
    for c in script.get("claims", []) or []:
        if c.get("is_clinical", True) and not (c.get("source_url") or "").strip():
            res.add(
                "uncited_clinical_claim",
                "block",
                f"clinical claim has no source: {c.get('text','')[:90]!r}",
                "script",
                "N.J.A.C. 13:30-6.2",
            )

    if mentions_pricing(f"{script.get('hook','')} {script.get('caption','')} "
                        + " ".join(str(l) for l in script.get("lines", []) or [])):
        res.add(
            "pricing_content", "block",
            "mentions fees or offers; route to the pricing approval path",
            "copy", "N.J.A.C. 13:30-6.2 - fee advertising",
        )

    res = check_media_consent(script.get("media", []) or [], client, conn=conn, result=res)

    dur = script.get("target_seconds")
    if isinstance(dur, (int, float)) and dur > 90:
        res.add("duration", "warn", f"target {dur}s is long for a Reel; watch time ratio suffers", "script")

    return res


# --------------------------------------------------------------- advisory LLM


DIGNITY_PROMPT = """You are a compliance reviewer for dental advertising in New Jersey.

N.J.A.C. 13:30-6.2 requires advertising be presented in a "dignified manner",
which it defines as not relying on techniques to obtain attention that depend
upon absurdity or demonstrate a clear and intentional lack of relevance to the
selection of a dentist. It also bars false, misleading or deceptive statements,
claims of superiority, and testimonials as to technical competence.

Review the content below. Be strict about absurdity and superiority, but do NOT
flag ordinary informative or reassuring content - explaining a procedure,
addressing anxiety, or correcting a myth is exactly what this rule permits.

Return JSON:
{"verdict": "pass" | "concern",
 "issues": [{"quote": "...", "why": "...", "suggested_fix": "..."}]}

CONTENT:
---
%s
---"""


def advisory_review(text: str) -> dict[str, Any]:
    """Optional second opinion from the LLM. Returns warnings only, never blocks."""
    from . import llm

    try:
        return llm.ask_json(DIGNITY_PROMPT % text[:6000], prefer="claude")
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "unavailable", "issues": [], "error": str(exc)}


def apply_advisory(res: ComplianceResult, text: str, where: str = "") -> ComplianceResult:
    review = advisory_review(text)
    if review.get("verdict") == "concern":
        for issue in review.get("issues", []) or []:
            res.add(
                "dignity_advisory",
                "warn",
                f"{issue.get('why','')} -> {issue.get('suggested_fix','')} "
                f"(quote: {issue.get('quote','')[:80]!r})",
                where,
                "N.J.A.C. 13:30-6.2 - dignified manner (advisory)",
            )
    return res

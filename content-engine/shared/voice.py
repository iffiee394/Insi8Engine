"""
Voice capture and AI-slop linting.

Adopted from the two reference builds (see content-systems-research/), which
independently landed on the same idea: a single voice file, built by having the
model INTERVIEW the client one question at a time and push back on vague
answers, then refined forever after by feeding back sentences you hated.

Two things are deliberately different here:

1. SEPARATION OF CONCERNS. Video 2 bakes per-platform formatting rules into the
   brand voice file. Video 1 argues voice should stay general and platform rules
   belong downstream. Video 1 is right - one file that answers both "who am I"
   and "how long should a LinkedIn hook be" gets edited for the wrong reason and
   drifts. Voice lives here; platform rules live in platforms.py.
   See DECISIONS.md D-21.

2. SLOP LINT IS SEPARATE FROM COMPLIANCE. Compliance blocks (a regulator cares).
   Slop only warns (a reader cares). Conflating them means a stylistic tic can
   halt a publish, and people then start disabling the gate that also catches
   the regulatory problems. See DECISIONS.md D-22.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ClientProfile

# --------------------------------------------------------------- slop tables

# Vocabulary that marks text as machine-written. Collected from both reference
# builds plus the usual suspects.
SLOP_WORDS = [
    "delve", "leverage", "seamless", "seamlessly", "unlock", "robust",
    "elevate", "game changer", "game-changer", "empower", "streamline",
    "tapestry", "landscape of", "realm of", "navigate the", "harness",
    "cutting-edge", "state-of-the-art", "revolutionize", "transformative",
    "in today's fast-paced", "dive deep", "deep dive", "unpack",
    "at the end of the day", "it's important to note", "let's face it",
    "look no further", "the truth is", "here's the thing",
]

# Sentence shapes that read as AI even when the words are fine.
SLOP_PATTERNS = [
    (r"\bnot\s+\w+[.,]\s*\w+\.", "the 'Not X. Y.' construction"),
    (r"\bthat'?s it\.\s*that'?s\b", "the \"That's it. That's the...\" tic"),
    (r"\bhere'?s the (uncomfortable|hard|real|honest) part\b", "the 'Here's the X part' pivot"),
    (r"\bit'?s not\b[^.!?]{1,40}?,\s*it'?s\b", "the 'It's not X, it's Y' reversal"),
    (r"\b(?:isn'?t|aren'?t|wasn'?t)\b[^.!?]{1,40}?,\s*it'?s\b", "the 'X isn't A, it's B' reversal"),
    (r"\bthe (whole|entire) (move|point|game|thing)\b", "the 'that's the whole move' close"),
    (r"[—–]", "em/en dash (models overuse it; people rarely type it)"),
    (r"\b\w+ isn'?t just \w+[,.]", "the 'X isn't just Y' escalation"),
    (r"^\s*(and|but)\s+here'?s\b", "the 'And here's...' paragraph opener"),
    (r"\blet that sink in\b", "'let that sink in'"),
    (r"\bwhat if I told you\b", "'what if I told you'"),
]

INTERVIEW_PROMPT = """You are going to interview me until you can write in my voice.

Rules for this interview:
- Ask ONE question at a time and wait for my answer.
- Maximum 8 questions.
- If my answer is vague or generic, push back and ask again. Do not move on politely.
- Do not summarise my answers back to me between questions.

Cover, in roughly this order:
1. Who I am and what the business actually does, in one sentence I would say out loud.
2. Who I am talking to, and what they are afraid of or confused about.
3. How I talk when I am explaining something to a nervous person face to face.
4. A phrase or two I actually say a lot.
5. Things I will never say, and why.
6. What I refuse to promise, exaggerate or imply.
7. A story or example I come back to.
8. What proof I am allowed to claim, and what I am not.

When the interview is finished, write the file below and nothing else.

OUTPUT FORMAT (markdown):
# Voice — {client_name}

## Identity
## Audience
## How I sound
## Phrases I use
## Words and patterns I never use
## What I will not claim
## Stories and proof I can use

CONSTRAINTS ON THE FINISHED FILE:
- Keep it general. Do NOT put platform-specific formatting rules in it
  (hook length, hashtag counts, character limits). Those live elsewhere.
- Never include: {slop_words}
- Never use an em dash.
- This is a regulated healthcare practice. The file must record that superlatives,
  guarantees, comparative claims and specialty implications are forbidden."""


REFINE_PROMPT = """Here is my current voice file:

{voice_file}

Here is a sentence the system produced that I did not like:

"{bad_sentence}"

Reason I disliked it: {reason}

Rewrite the "Words and patterns I never use" section of my voice file so this
pattern never appears again. Generalise from the example - ban the SHAPE, not
just this exact sentence. Return the complete updated voice file as markdown,
nothing else."""


@dataclass
class SlopFinding:
    kind: str
    hit: str
    note: str


def lint_slop(text: str) -> list[SlopFinding]:
    """Find machine-written tells. Warnings only, never blocking."""
    findings: list[SlopFinding] = []
    if not text:
        return findings
    low = text.lower()

    for word in SLOP_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", low):
            findings.append(SlopFinding("word", word, "overused by language models"))

    for pattern, note in SLOP_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            findings.append(SlopFinding("pattern", m.group(0)[:60], note))

    # Three or more consecutive very short sentences reads as AI cadence.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    run = 0
    for s in sentences:
        run = run + 1 if len(s.split()) <= 4 else 0
        if run >= 3:
            findings.append(SlopFinding(
                "cadence", s[:60], "three or more clipped sentences in a row"))
            break

    return findings


def slop_report(text: str) -> str:
    findings = lint_slop(text)
    if not findings:
        return "SLOP LINT: clean"
    lines = [f"SLOP LINT: {len(findings)} tell(s)"]
    for f in findings:
        lines.append(f"   WARN [{f.kind}] {f.hit!r} - {f.note}")
    return "\n".join(lines)


def voice_path(client: ClientProfile) -> Path:
    return client.root / "voice.md"


def load_voice(client: ClientProfile) -> str:
    """Prefer a real interview-built voice.md; fall back to client.json."""
    p = voice_path(client)
    if p.exists():
        return p.read_text(encoding="utf-8")
    v = client.voice
    return (
        f"# Voice — {client.name}\n\n"
        f"## Identity\n{v.get('persona','')}\n\n"
        f"## How I sound\nReading level: {v.get('reading_level','8th grade')}\n"
        f"{v.get('person','')}\n\n"
        f"## Phrases I use\n" + "\n".join(f"- {d}" for d in v.get("do", [])) + "\n\n"
        f"## Words and patterns I never use\n"
        + "\n".join(f"- {a}" for a in v.get("avoid", []))
        + "\n\n(Generated from client.json. Run `voice interview` for a real one.)\n"
    )


def interview_prompt(client: ClientProfile) -> str:
    return INTERVIEW_PROMPT.format(
        client_name=client.name,
        slop_words=", ".join(SLOP_WORDS[:14]),
    )


def refine_prompt(client: ClientProfile, bad_sentence: str, reason: str) -> str:
    return REFINE_PROMPT.format(
        voice_file=load_voice(client), bad_sentence=bad_sentence, reason=reason,
    )


def save_voice(client: ClientProfile, markdown: str) -> Path:
    p = voice_path(client)
    p.write_text(markdown, encoding="utf-8")
    return p


def append_banned_pattern(client: ClientProfile, bad_sentence: str, reason: str) -> Path:
    """Cheap local refinement: record the ban without an LLM round trip."""
    p = voice_path(client)
    current = load_voice(client)
    entry = f"- Never write anything shaped like: \"{bad_sentence.strip()}\" ({reason})\n"
    if "## Words and patterns I never use" in current:
        head, _, tail = current.partition("## Words and patterns I never use")
        lines = tail.split("\n")
        insert_at = 1
        current = head + "## Words and patterns I never use" + "\n".join(
            lines[:insert_at] + [entry.rstrip()] + lines[insert_at:]
        )
    else:
        current += f"\n\n## Words and patterns I never use\n{entry}"
    p.write_text(current, encoding="utf-8")
    return p

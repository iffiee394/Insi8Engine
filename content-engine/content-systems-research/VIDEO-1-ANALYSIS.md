# Video 1 — Step-by-step analysis

**"I Automated My Entire Content System With Claude Code (Full Build)"**
AI Foundations (Drake) · 363k subscribers · 66 minutes · published 6 Aug 2026 · 23.7k views
<https://youtu.be/hC00Qdhfjww>

Transcript: `_transcripts/video1-claude-code-content-system.txt` (14,213 words,
pulled with `youtube-transcript-api`).

---

## The stack

| Tool | Role | Cost |
|---|---|---|
| **Claude Code** | Engine: writer, designer, strategist, execution layer | $20/mo Pro (he is on $200 Max) |
| **FAL** (fal.ai) | Image/video generation aggregator; uses GPT Image 2 | pay-per-image, ~$0.003–0.03 each |
| **Blotato** | Publishing to 9 platforms | $29/mo starter (sponsor of the video) |

Stated total: **$60–70/month**. His framing: "this is basically your social media
marketing department."

---

## The five steps, as actually performed

### Step 1 — Set up the environment (~10 min)

1. Create a plain folder on the desktop — this is Claude Code's working directory.
2. Inside it, `assets/`, and inside that `images-of-me/`.
3. Fill it with **real photographs of himself**, descriptively named
   (`balcony-ocean-coffee`, `cafe-pink-laptop`) so Claude can pick an appropriate
   one per post.
4. Open the folder in Claude Code, trust workspace, enable auto mode.
5. Get a FAL API key, load $10–20 of credits, **turn auto-top-up off** ("just in
   case your model goes rogue").
6. Store the key in Claude Code's **local environment settings** as `FAL_KEY`,
   not in a file. "Claude never actually sees the key here, but it can use it."
7. Same for `BLOTATO_KEY`.
8. Connect social accounts inside Blotato via OAuth.

**Notable technique:** rather than using an MCP connector, he **pastes the tool's
API documentation URL into the chat**. His reasoning: "doing the documentation is
always faster once it understands it and it uses less context." Then he tells
Claude to bake the usage into an instruction file so it never has to be
re-explained.

**Notable warning, stated explicitly:** *"I see a lot of people now doing AI
generated images of everything of themselves and then their AI generated content
doesn't perform. There's a reason for that. The more human you can make something
look in an automated fashion, the better it's going to perform."*

### Step 2 — Ideation

- Find a style you like. Pinterest is his recommended source (search e.g.
  "health coach Instagram"), or reference a brand you admire.
- **2–3 contrasting colours, 2 fonts.** Keep it simple.
- Generate a cover image using a **real photo of himself** as the input, iterating
  in natural language ("skills a tad less tall, subtext in front of me, decrease
  contrast, keep the golden hue").
- Then the key move: **tell Claude to extract the style into a reusable
  instruction file.** He asks for two files — one for carousel covers
  specifically, one general file recording that he uses FAL and which model.
- Claude creates `instructions/`, `CLAUDE.md`, `image-styles/`, `references/`
  unprompted.

Result: he can later say *"use the golden hour editorial style on the picture of
me on the balcony"* and get consistent output.

His framing: *"Ideation is one of the bigger parts of this video because
everything else downstream stems from it."*

### Step 3 — Shape your voice

A free prompt that **interviews him**: *"Interview me until you can write like me.
Ask one question at a time and wait for my answer. Eight questions maximum. If the
answer is vague, push back and ask again. Do not move on politely."*

Produces `voice.md`. Then the refinement loop, which is the actually valuable
part — he reads generated posts and bans patterns he dislikes:

- the "Not this, this." construction
- "That's it. That's the whole thing."
- "Here's the uncomfortable part."
- "boring beats impressive", "that's the whole move"
- em dashes
- word list: *delve, leverage, seamless, unlock, robust, elevate, game changer,
  empower, streamline, tapestry*

Two structural points he makes:
- **Keep the voice file general.** Platform-specific rules (hook length etc.)
  belong "further down the pipeline into like a LinkedIn voice file."
- **Train on what already worked:** "if you're having it write something in your
  voice, use your past voice that's already worked."

### Step 4 — Build a carousel

1. Paste a YouTube transcript of his own pillar video.
2. Ask for a **5–6 slide concept with the beats per slide** and a CTA on the last
   slide (comment-keyword lead magnet: "comment CLAUDE and I'll send it over").
3. Edit the concept conversationally (he cuts a "proof" slide as premature).
4. Generate the **cover** with FAL using a real photo of himself.
5. For the **interior slides**, Claude pushes back and suggests **rendering them
   as HTML instead of paying for AI images** — cheaper and no elements that need
   generation. He agrees, then decides the pure-HTML version looks "like a
   corporate weird business slideshow you'd fall asleep during" and moves to a
   hybrid: FAL-generated backgrounds with text placed on them.
6. Feeds Blotato's **media requirements page** into Claude as context so it
   produces correct formats — PNG for Instagram, PDF for LinkedIn.
7. Schedules to both platforms from inside Claude Code.

### Step 5 — Automate it into a skill

He asks Claude to turn the whole session into a **skill**, invoked as
`/carousel-creator <YouTube URL>`.

Before doing so, he does something smart: he asks Claude to **extract its own
thought process** from the session. Claude's answer is the sharpest line in
either video:

> *"Almost nothing that went wrong today was a taste problem. It was mechanical.
> That should decide where you spend agents versus where you spend code…
> Only the last two need a model. Everything above them is code."*

The extracted pipeline:

```
transcript → concept → voice lint → photo pick → cover
          → plates → render → self-check → review → schedule
```

He also notes the skill can be run on a schedule, and that it ends with
*"nothing gets posted until you say go"* — though this is a prompt instruction
rather than an enforced control.

---

## What is genuinely good here

1. **The instruction-file pattern.** Doing it manually once, then having the model
   write its own reusable instructions, is the core reusability mechanism.
2. **Real photos, AI-enhanced.** Explicitly rejects fully synthetic imagery, and
   gives the correct reason (performance).
3. **HTML for information slides, generated imagery for covers.** Arrived at for
   cost reasons but it is also the right aesthetic call.
4. **The voice refinement loop.** Banning *shapes* rather than sentences.
5. **"Only the last two need a model."** The correct principle for where to spend
   an LLM versus deterministic code.
6. **Feeding platform media requirements as context** so formats come out right.

## What is missing or wrong for our use case

1. **No compliance concept whatsoever.** No claim sourcing, no ad archive, no
   approval gate. Fine for a personal brand; disqualifying for a dental practice.
2. **No fact-checking.** Safe only because he repurposes his own content. Applied
   to health topics this generates unsourced medical claims.
3. **"People want to see something they've already seen before with a different
   character behind it."** Stated with no originality check. This is exactly the
   near-duplicate pattern Instagram now demotes, and copying another practice's
   clinical claims is a real liability. See DECISIONS.md D-15.
4. **The safety rule is a prompt, not a control.** "Nothing gets posted until you
   say go" is a request the model can forget.
5. **No measurement.** Open loop: generate → post → done. Nothing learns.
6. **Ideation is manual Pinterest browsing.** No systematic competitor research
   despite that being the highest-leverage input.
7. **Single-caption output.** No per-platform tailoring (video 2 does this better).
8. **Cost is per-client and recurring** — $70/mo × 10 clients before revenue.

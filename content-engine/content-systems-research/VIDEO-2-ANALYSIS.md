# Video 2 — Step-by-step analysis

**"Claude Fable 5 Writes, Designs & Schedules All My Content Automatically"**
Zubair Trabzada | AI Workshop · 158k subscribers · 27.5 minutes · published 5 Jul 2026 · 38.9k views
<https://youtu.be/LmfIIpWgaFQ>

Transcript: `_transcripts/video2-fable5-content-system.txt` (5,921 words).

> **Note on your brief:** you wrote *"this video is table 5"* — it is **Fable 5**,
> the model he runs Claude Code on. You said we can use other models, and we do:
> this build uses Gemini as primary with Claude as fallback (DECISIONS.md D-04).

---

## The stack

| Tool | Role | Cost |
|---|---|---|
| **Claude Code (desktop app), model Fable 5, effort "extra"** | Engine | Pro plan minimum; he is on Max |
| **Higgsfield MCP** | Images and video — Nano Banana 2/Pro, GPT Image 2, Seedance, Veo 3.1, Kling | subscription; he concedes "a little expensive" |
| **Blotato MCP** | Publishing to 9 platforms | free trial then paid; **explicitly not sponsored** |

Pitch: *"It researches what's working in your niche, creates the images and the
videos, writes the post, and publishes to all nine platforms at once or on a
schedule in your brand voice. No code, no experience needed."*

---

## The steps, as actually performed

### Step 1 — Claude Code desktop, Fable 5, effort "extra"

Download the desktop app, Pro plan or above, open a Claude Code session. He sets
the model to Fable 5 and reasoning effort to "extra" ("a good little hybrid
approach, but you can keep it at high as well").

### Step 2 — Brand voice

Downloads a `brand_voice_template.md` from his free community, attaches it in
Claude Code, and pastes a prompt:

> *"I've attached my brand voice template. Interview me to fill it in. Ask one
> question at a time and push back when my answers are vague or generic."*

**This is essentially the same prompt as video 1**, arrived at independently.
The model asks section-by-section and offers multiple-choice options.

The template covers: identity, audience, offers and CTAs, voice rules, phrases,
stories, and **what proof you can claim**.

He does it once and reuses the file forever. (He retrieves his from a 3D
"operating system" with a voice assistant called Jarvis — a long product-plug
digression, not part of the method.)

**Key structural difference from video 1:** his brand voice file **contains
per-platform formatting rules**. Later in the video the model produces different
output per network *"based on that MD file… it actually gives it guidance that
for each platform, do something different that's tailored to that platform."*

### Step 3 — Connect Higgsfield via MCP

Settings → Connectors → Manage connectors → **Add custom connector** → paste the
remote MCP URL → Connect → OAuth authorise.

No API key handling at all. This is the main architectural difference from video 1
(which uses API keys plus pasted documentation).

His justification for the cost: *"this is the price of automation. If you want
complete automation, you got to pay for tools like this."*

### Step 4 — Connect Blotato via MCP

Same flow. Connect social accounts inside Blotato first (OAuth per network — he
demonstrates Twitter and TikTok), then add Blotato's remote MCP URL as a custom
connector.

Note he uses the **MCP connector**, not the API key, even though Blotato exposes
both.

### Step 5 — One prompt does everything

> *"Create a carousel type of post for my Instagram and LinkedIn and Twitter,
> each tailored to its own platform, use my brand voice, use the Higgsfield MCP
> to generate the images and the Blotato MCP to post it to all three accounts."*

Optionally he screenshots a carousel he likes and attaches it: *"for the carousel
design, use the attached image as a reference."*

The model checks both MCP connections, asks what the carousel should be about
(he had not specified), then generates six slides with Nano Banana Pro at 4:5 and
posts to all three networks.

**The per-platform result is the genuinely impressive part:**
- Instagram — "meme energy" caption, exactly five hashtags, comment CTA
- LinkedIn — ~1,400 character "builder story" ending on a business lesson
- Twitter/X — its own variant

All from one brand voice file and one prompt.

### Step 6 — Scheduling

Two routes offered: Claude's native **routines** (set a recurring time), or a
third prompt from his pack — *"read my brand_voice.md, ask me three questions,
but for the week"* — to plan a week at once.

He notes video generation works the same way but *"it's going to cost you more
tokens and more money. Images are always cheaper and these carousels do really,
really well."*

Closing tip: when something breaks, screenshot the error and hand it back —
*"that's what Fable 5 was really good at, problem-solving."*

---

## What is genuinely good here

1. **Per-platform tailoring from one voice file.** The strongest idea in either
   video. One source caption → correctly shaped output per network.
2. **MCP connectors instead of API keys.** Less setup, no secrets in prompts,
   OAuth-scoped. Genuinely simpler than video 1's approach.
3. **Reference-image attachment** to lock visual style — one screenshot replaces
   a long style description.
4. **Fastest path to a first post.** ~27 minutes end to end versus 66.
5. **Independent convergence on Blotato and on the interview-built voice file.**
   Two creators, no shared incentive (he is explicitly not sponsored), same
   answer — that is a real signal.

## What is missing or wrong for our use case

1. **No compliance layer.** Same fatal gap as video 1.
2. **No grounding at all.** Video 1 at least repurposes a real transcript. Here
   content is generated from the brand-voice file alone, with **no source for any
   factual claim**. For dental content this is the most dangerous property of
   either system.
3. **The headline claim is not demonstrated.** *"It researches what's working in
   your niche"* — no research step is ever shown or built. This is the gap Part D
   actually fills.
4. **It posts immediately.** No draft state, no approval, no human gate. Video 1
   at least states the rule.
5. **Platform rules inside the voice file.** Convenient now, drifts later. See
   DECISIONS.md D-21 for why this build separates them.
6. **Fully synthetic imagery.** No equivalent of video 1's "use real photos of
   yourself" warning — and video 1 is right about this.
7. **Most expensive stack of the three.** Claude Max + Higgsfield + Blotato.
8. **Significant runtime is product placement** for a paid community.

# Urdu & Mixed Language Support — How It Actually Works

> This explains the exact mechanism for handling Urdu, Roman Urdu (Urdu in English letters), and mixed Urdu-English podcasts. These are common in Pakistani podcast culture where speakers freely switch between languages mid-sentence.

---

## The problem, traced step by step

Take a real scenario: you add a podcast from Junaid Akram or Muzamil Hassan where they're discussing AI in mixed Urdu-English. Here's what happens today vs. what should happen.

### Step 1: Audio download (yt-dlp)

**Today:** Works fine. Language doesn't matter here — audio is audio.

**No change needed.**

---

### Step 2: Transcription — this is where everything breaks

The pipeline tries two paths in order:

#### Path A: YouTube captions (`pipeline.py → _fetch_youtube_captions`)

**Today (broken):**
```python
# Current code tries these languages, in order:
for lang in ("en", "en-US", "en-GB"):
    transcript = transcript_list.find_transcript([lang])
```
Then falls back to English auto-generated, then whatever's first.

**What goes wrong:**
- For an Urdu podcast, English captions don't exist
- YouTube might have auto-generated Urdu captions (YouTube added Urdu ASR in 2023) — but the code never asks for them
- The code falls through to `next(iter(transcript_list))` which MIGHT pick Urdu auto-captions by accident, or might pick some other language
- If it does get Urdu captions, they'll be in Urdu script (نستعلیق) — which the LLM can sort-of read but much worse than English

**Fix — try the user's language first:**
```python
def _fetch_youtube_captions(video_id: str, languages: list[str] | None = None) -> str | None:
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None

        # 1. Try user's preferred languages first
        preferred = languages or []
        for lang in preferred:
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except Exception:
                continue

        # 2. Then try English
        if transcript is None:
            for lang in ("en", "en-US", "en-GB"):
                try:
                    transcript = transcript_list.find_transcript([lang])
                    break
                except Exception:
                    continue

        # 3. Then try auto-generated in preferred or English
        if transcript is None:
            try_langs = preferred + ["en"]
            try:
                transcript = transcript_list.find_generated_transcript(try_langs)
            except Exception:
                transcript = next(iter(transcript_list))

        segments = transcript.fetch()
        text = " ".join(seg.get("text", "") for seg in segments if seg.get("text"))
        return text.strip() or None
    except Exception:
        return None
```

For an Urdu playlist, `languages=["ur", "hi"]` is passed in. This means:
1. First check: does the video have manual Urdu or Hindi captions? (Best quality)
2. Then check: English captions? (Won't exist for Urdu podcasts usually)
3. Then check: auto-generated Urdu/Hindi captions? (YouTube has these now — decent quality)
4. Last resort: whatever's available

**Where does `languages` come from?** The user's profile (see Step 5 below).

#### Path B: Groq Whisper fallback (`transcriber.py → transcribe_youtube_audio`)

If no YouTube captions exist, the pipeline downloads audio and sends it to Groq Whisper.

**Today (broken):**
```python
# Current code — no language hint at all
result = client.audio.transcriptions.create(
    file=(media_path.name, media_file.read()),
    model="whisper-large-v3-turbo",
    response_format="text",
)
```

**What goes wrong with mixed Urdu-English:**
- Whisper auto-detects language from the first 30 seconds
- If the host starts in Urdu, Whisper thinks "this is Urdu" and tries to write EVERYTHING in Urdu script — English words get transliterated into Urdu (garbage)
- If the host starts in English, Whisper thinks "this is English" and tries to write Urdu words as English sounds (also garbage)
- Code-switching (mixing mid-sentence) is the hardest case for any speech model

**Fix — use Whisper's `language` and `prompt` parameters:**

```python
def transcribe_file(media_path: Path | str, *, language: str = "", transcription_prompt: str = "") -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    media_path = Path(media_path)
    client = Groq(api_key=api_key)

    kwargs = {
        "file": (media_path.name, open(media_path, "rb").read()),
        "model": "whisper-large-v3-turbo",
        "response_format": "text",
    }

    # Language hint — tells Whisper what language to expect
    if language:
        kwargs["language"] = language

    # Prompt hint — guides transcription style and code-switching behavior
    if transcription_prompt:
        kwargs["prompt"] = transcription_prompt

    result = client.audio.transcriptions.create(**kwargs)
    return str(result).strip()
```

**The key insight: the `prompt` parameter.**

Whisper's `prompt` parameter isn't a system prompt — it's a "style hint" that tells the model what kind of text to produce. For mixed Urdu-English, this is the critical piece:

```python
MIXED_URDU_ENGLISH_PROMPT = (
    "This is a Pakistani podcast where speakers mix Urdu and English freely. "
    "Transcribe all English words in English. "
    "Transcribe Urdu words in Roman Urdu (Latin script, not Urdu script). "
    "Example: 'Bhai yeh AI ka future bohot bright hai, machine learning mein bohot scope hai.' "
    "Keep code-switching natural — don't force everything into one language."
)
```

**Why Roman Urdu?** Because:
- LLaMA 3.3 understands English perfectly
- LLaMA 3.3 can read Roman Urdu reasonably well (it's written in Latin letters, like English)
- LLaMA 3.3 struggles with Urdu script (نستعلیق) — limited training data
- So: Roman Urdu output from Whisper → LLM can actually understand it

**What the transcript looks like with this fix:**

Without fix (broken):
```
"یہ AI کا فیوچر بہت برائٹ ہے machine learning میں بہت scope ہے"
(Mixed Urdu script + English — LLM can barely read this)
```

With fix (Roman Urdu):
```
"Bhai yeh AI ka future bohot bright hai, machine learning mein bohot scope hai."
(All Latin script — LLM understands this well)
```

---

### Step 3: LLM extraction — needs to know the language

**Today (broken):**
The prompts assume pure English transcripts. If the transcript is in Roman Urdu, the LLM might:
- Ignore Urdu words it doesn't understand
- Misinterpret Roman Urdu as misspelled English
- Lose context from Urdu portions

**Fix — add a language context block to prompts:**

In `pipeline.py`, the `_build_language_context()` function:

```python
def _build_language_context(languages: list[str]) -> str:
    """Build a language instruction block for LLM prompts."""
    if not languages or languages == ["en"]:
        return ""

    lang_names = {
        "ur": "Urdu",
        "hi": "Hindi", 
        "pa": "Punjabi",
        "en": "English",
    }
    
    names = [lang_names.get(l, l) for l in languages]
    
    if len(names) == 1 and names[0] != "English":
        return f"""LANGUAGE NOTE: This transcript is in {names[0]}. The content may be in {names[0]} script or romanized (Latin letters). Understand it fully and extract all insights in English. Do not skip or ignore non-English portions — they often contain the most important content.\n"""
    
    return f"""LANGUAGE NOTE: This transcript mixes {', '.join(names)}. Speakers switch between languages mid-sentence (code-switching). This is normal — understand ALL portions regardless of language. Roman Urdu (Urdu written in English letters like "bohot acha hai") should be understood as Urdu. Extract all insights in English.\n"""
```

This block gets prepended to every LLM prompt (recon, extraction, chat). Example of what the LLM sees:

```
LANGUAGE NOTE: This transcript mixes Urdu, English. Speakers switch between 
languages mid-sentence (code-switching). This is normal — understand ALL portions 
regardless of language. Roman Urdu (Urdu written in English letters like 
"bohot acha hai") should be understood as Urdu. Extract all insights in English.

USER PROFILE — use this to shape your extraction:
---
About the user: I'm a CS student working in AI...
---

You are extracting deep, comprehensive insights from a podcast titled "..."
...
```

---

### Step 4: Research — works mostly, small adjustment

**Today:** Tavily searches in English only.

**What goes wrong:** For Pakistani/Urdu-speaking guests who are famous in Urdu-speaking circles but not well-known globally, English search results may be thin.

**Fix — add Urdu search queries:**

In `researcher.py`, when the language context suggests Urdu content:

```python
def _research_person(name: str, languages: list[str] | None = None) -> dict:
    if not name:
        return {}
    
    queries = [
        f'"{name}"',
        f'"{name}" viral OR trending OR famous for',
        f'"{name}" site:reddit.com',
        f'"{name}" interview highlights OR controversial',
    ]
    
    # Add Urdu-context searches if relevant
    if languages and any(l in ("ur", "hi", "pa") for l in languages):
        queries.extend([
            f'"{name}" Pakistan OR Pakistani',
            f'"{name}" podcast urdu',
        ])
    
    search_text = _collect_search_results(queries)
    # ... rest is the same
```

This ensures we find results for guests who are well-known in Pakistan but might not surface with generic English queries.

---

### Step 5: Where the language setting lives — the profile

Add a `languages` field to the user profile:

```json
{
    "about_me": "I'm a CS student working in AI...",
    "interests": "Deep technical details, personality insights...",
    "insight_style": "Specific names, tools, numbers...",
    "known_topics": "Python basics, REST APIs...",
    "languages": ["en", "ur"]
}
```

**In the dashboard (`app.py`)**, add a language selector to the profile editor:

```python
LANGUAGE_OPTIONS = {
    "en": "English",
    "ur": "Urdu",
    "hi": "Hindi",
    "pa": "Punjabi",
    "ar": "Arabic",
}

# Inside the profile expander:
current_langs = profile.get("languages", ["en"])
selected_langs = st.multiselect(
    "Podcast languages",
    options=list(LANGUAGE_OPTIONS.keys()),
    default=current_langs,
    format_func=lambda k: LANGUAGE_OPTIONS.get(k, k),
    help="Select all languages your podcasts use. For mixed Urdu-English, select both.",
)
```

**How it flows through the pipeline:**

```
Profile: languages = ["en", "ur"]
    ↓
poll.py: passes languages to process_video()
    ↓
pipeline.py → _fetch_youtube_captions(video_id, languages=["ur", "en"])
    → tries Urdu captions first, then English
    ↓
If no captions → transcriber.py → transcribe_file(
    audio_path,
    language="ur",
    transcription_prompt="This is a Pakistani podcast mixing Urdu and English..."
)
    → Whisper outputs Roman Urdu + English
    ↓
pipeline.py → _recon_pass(transcript, title)
    → prompt includes: "LANGUAGE NOTE: This transcript mixes Urdu, English..."
    → LLM understands Roman Urdu, extracts guest name, topics
    ↓
pipeline.py → _holistic_extraction(...)
    → same language note in prompt
    → LLM extracts insights in English from the mixed transcript
    ↓
Dashboard shows insights in English ✅
```

---

## Concrete example: before and after

### Podcast: Junaid Akram discussing "AI aur Pakistan ka future" with a tech guest

**BEFORE (current system):**

1. YouTube captions: looks for English → finds nothing useful
2. Whisper: auto-detects Urdu → outputs Urdu script → `یہ AI کا فیوچر...`
3. LLM: gets Urdu script → barely understands → shallow/broken insights
4. **Result: "The guest discussed artificial intelligence." (useless)**

**AFTER (with language support):**

1. YouTube captions: looks for Urdu first → finds Urdu auto-captions ✅ (or manual if available)
2. If no captions → Whisper with prompt → outputs: `"Bhai AI ka future Pakistan mein bohot bright hai, especially machine learning aur data science mein. Humare paas talent hai but infrastructure ki kami hai..."` ✅
3. LLM: gets language note + Roman Urdu transcript → fully understands
4. **Result:**
   - 📌 **AI landscape in Pakistan**: The guest argues Pakistan has world-class ML talent (mentions LUMS, NUST, FAST graduates working at Google, Meta) but lacks compute infrastructure. Specifically mentioned that AWS and Azure data centers are not in Pakistan, causing 200ms+ latency for Pakistani AI startups...
   - 📌 **Career advice for CS students**: Recommends focusing on MLOps over pure research — "research papers likhne se job nahi milti, production mein model deploy karna seekho" (writing papers won't get you a job, learn to deploy models in production)...
   - 💡 **Guest's personal story**: Dropped out of a US master's program to return to Pakistan, built a startup that was acqui-hired by Careem...

---

## What changes in the code

| File | What changes | Size |
|------|-------------|------|
| `db.py` | Add `languages` field to profile schema | 2 lines |
| `pipeline.py` | Add `_build_language_context()`, pass `languages` to caption fetch + Whisper + all prompts | ~30 lines |
| `transcriber.py` | Add `language` and `prompt` params to `transcribe_file()` and `transcribe_youtube_audio()` | ~15 lines |
| `researcher.py` | Add language-aware search queries for guests and topics | ~10 lines |
| `app.py` | Add language multiselect to profile editor | ~10 lines |

**Total: ~65 lines of changes across 5 files.** No new dependencies, no new API keys.

---

## Language support quality matrix

| Content type | Transcription | LLM understanding | Overall |
|-------------|---------------|-------------------|---------|
| Pure English | Excellent | Excellent | ⭐⭐⭐⭐⭐ |
| Pure Urdu (with Roman Urdu Whisper hint) | Good | Good | ⭐⭐⭐⭐ |
| Mixed Urdu-English (with hint) | Good | Good | ⭐⭐⭐⭐ |
| Mixed Urdu-English (without hint) | Poor | Poor | ⭐⭐ |
| Pure Urdu script (no Roman conversion) | Decent | Weak | ⭐⭐⭐ |

The Roman Urdu approach is the key — it converts the problem from "LLM must read Urdu script" (hard) to "LLM must read Urdu words written in English letters" (much easier, since the letters are familiar).

---

## Limitations (being honest)

1. **Whisper's Roman Urdu isn't perfect.** It might spell the same word differently each time: "bohot" vs "bohat" vs "bahut". LLMs handle this okay but it's not clean.

2. **Heavily Urdu-dominant podcasts** (90%+ Urdu with rare English) will produce lower quality insights than English ones. LLaMA 3.3 simply has more English training data.

3. **Urdu wordplay, poetry, and cultural references** will often be lost. If the host quotes Ghalib or makes a pun in Urdu, Whisper may garble it and the LLM won't catch the cultural significance.

4. **Names in Urdu** can get mangled by Whisper. "Muhammad Asad" might come out as "Mohammad Assad" or similar variants, which could affect guest research accuracy.

5. **No Urdu output option yet.** Insights are always extracted in English. If you want Urdu insights, that's a separate feature (change the extraction prompt to output in Urdu).

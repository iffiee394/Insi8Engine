# PLAN-chat-tab — Wire the "Ask anything about this video" chat to the existing backend

**Rank: 3 of 5.** The backend is one finished function; the work is the iframe↔Streamlit round trip.

## Goal

The Library detail pane (`components/stitch_pages.py::_detail_pane`) has a Chat tab that says "Chat coming soon." and a chat input at the bottom of the pane that does nothing. The backend already exists: `pipeline.py::chat_with_video(video_id, user_message, chat_history)` answers questions from the full transcript and returns a string (verified at `pipeline.py:819`). After this plan, typing a question and pressing Enter (or the send button) runs the model and shows the conversation in the Chat tab.

## Architecture context

- Pages are complete HTML documents in `st.components.v1.html()` iframes ("Option D"). No Streamlit widgets. The ONLY channel from iframe to Python is the parent URL: JS calls `_nav({...})` (in `_NAV_BRIDGE`, `components/stitch_pages.py`), setting `window.parent.location.search`, which reruns Streamlit; `components/ui_shell.py::_read_query_params()` reads the params.
- Follow the existing `action=save` handler in `_read_query_params()` as the pattern for handling an action param and then clearing it.
- `chat_with_video` is synchronous and takes several seconds (one LLM call over the full transcript). The rerun that carries the chat param will block for that long — acceptable; show a spinner.

## Design

Chat history lives in `st.session_state.chat_histories` — a dict `{video_id: [{"role": "user"|"assistant", "content": str}, ...]}`. It is session-only (lost on app restart); that matches the legacy behavior in `app.py` (line ~856) and is fine.

Flow: user types question → JS navigates to `?page=library&vid=<id>&chat=<question>` → Streamlit rerun → `_read_query_params()` calls the pipeline, appends both messages to history, clears the `chat` param → `render_library_page` re-renders with the conversation in the Chat tab and forces that tab active for the selected video.

## Files to touch, in order

### Step 1 — `components/ui_shell.py`: handle the `chat` param

In `_read_query_params()`, add after the existing handlers:

```python
chat_msg = params.get("chat", "").strip()
if chat_msg and vid:
    if "chat_histories" not in st.session_state:
        st.session_state.chat_histories = {}
    history = st.session_state.chat_histories.setdefault(vid, [])
    from pipeline import chat_with_video
    with st.spinner("Thinking..."):
        answer = chat_with_video(vid, chat_msg, history)
    history.append({"role": "user", "content": chat_msg})
    history.append({"role": "assistant", "content": answer})
    st.session_state.chat_open_vid = vid
    st.query_params.clear()
    st.query_params["page"] = "library"
    st.query_params["vid"] = vid
```

Note the ordering: `chat_with_video` receives the history WITHOUT the new question (it appends the question itself in the prompt); append to history only after the call, mirroring the legacy flow.

Also ensure `vid` here is the same variable already read from `params.get("vid", "")` earlier in the function.

### Step 2 — `components/ui_shell.py`: pass histories into the renderer

Change the library/queue routing calls to pass two new arguments:

```python
render_library_page(
    all_videos,
    selected_id=st.session_state.get("selected_id"),
    active_tab="library",
    chat_histories=st.session_state.get("chat_histories", {}),
    open_chat_vid=st.session_state.pop("chat_open_vid", None),
)
```

(`pop` so the Chat tab is only force-opened on the rerun right after an answer.)

### Step 3 — `components/stitch_pages.py`: render the conversation

1. Add parameters `chat_histories: dict | None = None, open_chat_vid: str | None = None` to `render_library_page`, defaulting to None. Pass the per-video history into `_detail_pane(video, chat_history=...)`.
2. In `_detail_pane`, replace the `tab-chat` placeholder with rendered messages:
   - User message: right-aligned bubble, `bg-on-secondary-fixed-variant text-white rounded-xl px-3 py-2 max-w-[75%] ml-auto text-[13px]`.
   - Assistant message: left-aligned, `bg-surface border border-border rounded-xl px-3 py-2 max-w-[75%] text-[13px] text-text-primary`.
   - Escape all content with `_e()` and convert newlines to `<br/>` AFTER escaping.
   - Empty history → keep a friendly hint: "Ask anything about this video — answers come from the full transcript."
3. Wire the existing bottom textarea + send button (they're already in `_detail_pane`): give the textarea `id="chat-input-{vid_id}"`, give the send button `onclick="sendChat('{vid_id}')"`, and add to the textarea `onkeydown="if(event.key==='Enter'&&!event.shiftKey){{event.preventDefault();sendChat('{vid_id}');}}"` (note the doubled braces — this sits inside an f-string).
4. Add to the page script in `render_library_page`:

```js
function sendChat(vid) {
  var t = document.getElementById('chat-input-' + vid);
  if (!t || !t.value.trim()) return;
  var btn = t.parentElement.querySelector('button');
  if (btn) btn.innerHTML = '<span class="material-symbols-outlined text-[18px]" style="animation:spin 1s linear infinite">progress_activity</span>';
  t.disabled = true;
  _nav({page:'library', vid: vid, chat: t.value.trim().slice(0, 1200)});
}
```

5. Force-open the Chat tab after an answer: at the end of the page script, add

```js
var _openChat = __OPEN_CHAT_JSON__;
if (_openChat) {
  var nav = document.querySelector('#detail-container nav');
  if (nav) {
    var btns = nav.querySelectorAll('button');
    if (btns.length) switchTab(btns[btns.length - 1], 'tab-chat');
  }
  var tc = document.getElementById('tab-content');
  if (tc) tc.scrollTop = tc.scrollHeight;
}
```

where `__OPEN_CHAT_JSON__` is substituted in Python with `json.dumps(bool(open_chat_vid and open_chat_vid == selected_id))`. The Chat button is the last button in the tabs nav — that's why `btns[btns.length-1]` works; don't change tab order.

## Edge cases a weaker model would miss

1. **Clear the `chat` param or it re-fires.** Every rerun re-reads query params; without the `clear()` + re-set shown in Step 1, one question would be re-asked (and re-billed) on every subsequent rerun, including the automatic ones from the 3-second queue-tick fragment.
2. **The queue-tick fragment reruns while you wait.** `_queue_tick` runs every 3 s but is a fragment — it does not re-execute `_read_query_params()`, so it won't double-fire the chat call. Do not "fix" this; just be aware.
3. **URL length.** The question travels in the URL. Cap at 1200 chars in JS (`.slice(0,1200)`). `URLSearchParams` percent-encodes everything (spaces, newlines, `&`, unicode) and Streamlit decodes automatically — never decode twice.
4. **History grows the page.** `_detail_pane` output is embedded twice (inline + `details_json` blob). Long chats inflate the payload; cap rendering at the last 20 messages (`history[-20:]`). `chat_with_video` itself already caps its prompt at the last 10.
5. **Selecting another video client-side.** `selectVideoLocal` swaps panes without a Streamlit rerun, so another video's chat history is whatever was rendered at page build — correct, since histories were passed for ALL videos. Make sure Step 3.1 passes each video its own history when building `all_details`, not just the selected one.
6. **No transcript / not-done videos.** `chat_with_video` handles missing transcripts gracefully (returns a message string). Still, only render the chat input for `STATUS_DONE` videos — for other statuses the pane doesn't show the input anyway (see PLAN-restore-actions).
7. **`json.dumps` for the flag,** not Python's `True`/`False` (JS needs lowercase `true`/`false`).

## Do not touch

- `transcriber.py`, `youtube_monitor.py`.
- `pipeline.py` — call `chat_with_video` as-is; do not modify its prompt or signature.
- Insights tab and `selectVideoLocal` mechanics.
- New work must not break or restructure existing files or the working pipeline. Extend, don't rewrite.

## Acceptance criteria

Run `cd "D:\Cursor Projects\CursorP1"; python -m streamlit run app.py`, open http://localhost:8501, select a **done** video.

1. Typing a question in the bottom input and pressing Enter shows a spinner, then the page returns with the Chat tab open showing your question and a transcript-grounded answer.
2. The send button (paper-plane icon) does the same as Enter; Shift+Enter inserts a newline instead of sending.
3. Asking a follow-up ("what else did they say about that?") produces an answer that uses the previous exchange (history is passed).
4. Asking about something not in the video gets an honest "the transcript doesn't cover this" style answer.
5. Refreshing the browser keeps the history for the session; restarting Streamlit clears it (expected).
6. After the answer, the URL contains only `?page=library&vid=...` (no `chat=` remnant), and no duplicate answers appear over the next 10 seconds of idling.

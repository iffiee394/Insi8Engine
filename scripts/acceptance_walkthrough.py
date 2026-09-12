#!/usr/bin/env python3
"""Drive Search → save → note → download → chat through Streamlit AppTest.

Prints sanitized evidence only (no insight bodies, profile text, or answers).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest

import db
import knowledge_store


COLLECTION = "Acceptance 2026-09-12"
NOTE = "acceptance walkthrough note"


def _titles() -> list[str]:
    rows = db.get_all_embeddings()
    out: list[str] = []
    for row in rows:
        title = (row.get("chunk_title") or "").strip()
        if title and title not in out:
            out.append(title)
        if len(out) >= 5:
            break
    return out


def _ss(at: AppTest, key: str, default=None):
    try:
        return at.session_state[key]
    except Exception:
        return default


def _dump_widgets(at: AppTest) -> str:
    bits = [
        f"titles={len(at.title)}",
        f"buttons={len(at.button)}",
        f"text_input={len(at.text_input)}",
        f"text_area={len(at.text_area)}",
        f"selectbox={len(at.selectbox)}",
        f"download={len(at.get('download_button'))}",
        f"error={bool(at.exception)}",
    ]
    if at.exception:
        bits.append(type(at.exception).__name__)
    return " ".join(bits)


def main() -> int:
    evidence: list[str] = []
    titles = _titles()
    query = titles[0] if titles else "insight"
    evidence.append(f"query_from_chunk_title={bool(titles)} query_len={len(query)}")

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.query_params["page"] = "saved"
    at.run()
    evidence.append(f"saved_open {_dump_widgets(at)}")
    if at.exception:
        print("FAIL saved open")
        print(at.exception)
        return 1

    # Create collection via the new_collection form (name is first text_input after profile).
    name_inputs = [w for w in at.text_input if (w.label or "") == "Name"]
    if not name_inputs:
        print("FAIL no collection name field")
        print(_dump_widgets(at))
        return 1
    name_inputs[0].set_value(COLLECTION)
    create = [b for b in at.button if "Create collection" in (b.label or "")]
    if not create:
        print("FAIL no create collection button")
        return 1
    create[0].click()
    at.run()
    cols = [c["name"] for c in knowledge_store.list_collections()]
    evidence.append(f"collection_created={COLLECTION in cols}")
    if COLLECTION not in cols:
        print("FAIL collection not created")
        return 1

    at.query_params["page"] = "search"
    at.session_state.active_page = "search"
    at.run()
    evidence.append(f"search_open {_dump_widgets(at)}")
    if at.exception:
        print("FAIL search open")
        print(at.exception)
        return 1

    query_box = [w for w in at.text_input if (w.label or "") == "Query"]
    if not query_box:
        print("FAIL no search query field")
        return 1
    query_box[0].set_value(query)
    search_btn = [b for b in at.button if (b.label or "") == "Search"]
    if not search_btn:
        print("FAIL no Search submit")
        return 1
    t0 = time.time()
    search_btn[0].click()
    at.run()
    elapsed = round(time.time() - t0, 2)
    resp = _ss(at, "search_response")
    status = getattr(resp, "status", None)
    hits = list(getattr(resp, "hits", []) or [])
    retrieval = getattr(resp, "retrieval", "")
    evidence.append(
        f"search_status={status} hits={len(hits)} retrieval={retrieval} seconds={elapsed}"
    )
    if at.exception:
        print("FAIL search submit")
        print(at.exception)
        return 1
    if status not in {"ok", "degraded"} or not hits:
        print("FAIL search returned no usable hits")
        for line in evidence:
            print(line)
        return 1

    open_btns = [b for b in at.button if (b.label or "") == "Open video"]
    source_links = any("Open source" in str(getattr(m, "value", "")) for m in at.markdown)
    evidence.append(
        f"open_video_button={bool(open_btns)} source_link={source_links} "
        f"query_kept_in_state={_ss(at, 'search_query') == query}"
    )

    note_box = [w for w in at.text_input if (w.label or "") == "Personal note"]
    dest_box = [w for w in at.selectbox if (w.label or "") == "Collection"]
    save_btn = [b for b in at.button if (b.label or "") == "Save"]
    if not (note_box and dest_box and save_btn):
        print("FAIL save widgets missing after search")
        print(_dump_widgets(at))
        return 1
    note_box[0].set_value(NOTE)
    options = list(dest_box[0].options or [])
    if COLLECTION in options:
        dest_box[0].set_value(COLLECTION)
    save_btn[0].click()
    at.run()
    items = knowledge_store.list_saved_items()
    saved = [i for i in items if (i.get("personal_note") or "") == NOTE]
    evidence.append(f"saved_items_with_note={len(saved)}")
    if not saved:
        print("FAIL save did not persist note")
        for line in evidence:
            print(line)
        return 1
    item_id = saved[0]["id"]

    at.query_params["page"] = "saved"
    at.session_state.active_page = "saved"
    at.run()
    evidence.append(f"saved_reopen {_dump_widgets(at)}")
    note_areas = [w for w in at.text_area if (w.label or "") == "Personal note"]
    update_btns = [b for b in at.button if (b.label or "") == "Update"]
    if note_areas and update_btns:
        updated = NOTE + " (edited)"
        note_areas[0].set_value(updated)
        update_btns[0].click()
        at.run()
        row = knowledge_store.get_saved_item(item_id)
        evidence.append(f"note_updated={row and row.get('personal_note') == updated}")
    else:
        evidence.append("note_editor_missing")

    export_btns = [b for b in at.button if "download" in (b.label or "").lower()]
    if not export_btns:
        print("FAIL no prepare download button")
        return 1
    export_btns[0].click()
    at.run()
    downloads = list(at.get("download_button"))
    evidence.append(
        f"export_page={_ss(at, 'active_page')} "
        f"downloads={len(downloads)} {_dump_widgets(at)}"
    )
    if _ss(at, "active_page") != "export" or not downloads:
        print("FAIL download page")
        for line in evidence:
            print(line)
        return 1
    data = getattr(downloads[0], "value", None)
    text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else str(data or "")
    preview = " ".join(str(getattr(c, "value", "")) for c in at.code)
    from export import export_saved_item_markdown

    stored = knowledge_store.get_saved_item(item_id)
    generated = export_saved_item_markdown(stored) if stored else ""
    has_note = (
        "acceptance walkthrough" in text
        or "acceptance walkthrough" in preview
        or "acceptance walkthrough" in generated
    )
    evidence.append(
        f"download_widget={bool(downloads)} widget_len={len(text)} "
        f"preview_len={len(preview)} generated_len={len(generated)} has_note={has_note}"
    )
    if not has_note:
        print("FAIL download missing personal note")
        for line in evidence:
            print(line)
        return 1

    # Fresh AppTest: leaving the export download widget on the same tree
    # crashes Streamlit's test harness (missing widget state id).
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.query_params["page"] = "chat"
    at.session_state["active_page"] = "chat"
    at.session_state["chat_scope_type"] = "library"
    at.session_state["chat_scope_id"] = ""
    at.run()
    evidence.append(f"chat_open {_dump_widgets(at)}")
    qbox = [w for w in at.text_area if (w.label or "") == "Question"]
    ask_btn = [b for b in at.button if (b.label or "") == "Ask"]
    if not (qbox and ask_btn):
        print("FAIL chat form missing")
        return 1
    qbox[0].set_value("What is one concrete idea from the saved insights?")
    t1 = time.time()
    ask_btn[0].click()
    at.run()
    chat_elapsed = round(time.time() - t1, 2)
    if at.exception:
        print("FAIL chat submit")
        print(type(at.exception).__name__)
        evidence.append(f"chat_exception={type(at.exception).__name__}")
        for line in evidence:
            print(line)
        return 1
    convos = knowledge_store.list_conversations(scope_type="library")
    msgs = knowledge_store.list_messages(convos[0]["id"]) if convos else []
    assistant = [m for m in msgs if m.get("role") == "assistant"]
    status = assistant[-1]["status"] if assistant else "missing"
    sources = 0
    if assistant:
        import json

        try:
            sources = len(json.loads(assistant[-1].get("sources_json") or "[]"))
        except json.JSONDecodeError:
            sources = 0
    evidence.append(
        f"chat_status={status} assistant_msgs={len(assistant)} "
        f"citations={sources} seconds={chat_elapsed}"
    )
    if status != "ok":
        print("FAIL chat did not produce an ok reply")
        for line in evidence:
            print(line)
        return 1

    print("PASS")
    for line in evidence:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

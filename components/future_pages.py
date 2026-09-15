"""Deferred features: semantic Search, Saved items, and library Chat.

These are complete and tested, but intentionally out of the main navigation
while the app focuses on its core loop: add a video, spend quota on insights,
read them in the library. See docs/knowledge-system/FUTURE_PLAN.md.

Nothing here is wired into the nav. The routes still resolve, so
`?page=search`, `?page=saved` and `?page=chat` remain reachable for
development, and this module is where the next iteration builds from.
"""

from __future__ import annotations

import html
import json
import re
import uuid

import streamlit as st

import db
import dbcache
import config
import knowledge_store
from components.knowledge_pages import native_page_css, render_native_nav, _safe_filename
from components.navigation import navigate, page_button
from export import (
    export_collection_markdown,
    export_saved_item_markdown,
    export_video_markdown,
)
from knowledge_chat import ask, safe_http_url, youtube_watch_url
from search import SearchResponse, search_insights_response


def render_home_page(videos: list[dict]) -> None:
    st.markdown(native_page_css(), unsafe_allow_html=True)
    render_native_nav("home")
    st.markdown('<div class="ie-home"><h1>Find an idea.</h1>'
                '<p>Search the videos you’ve saved.</p></div>', unsafe_allow_html=True)
    with st.form("home_search"):
        query = st.text_input("Search your knowledge", placeholder="A topic, a question, something you remember…",
                              label_visibility="collapsed")
        submitted = st.form_submit_button("Search", type="primary")
    if submitted and query.strip():
        st.session_state.search_query = query.strip()
        with st.spinner("Searching your library…"):
            st.session_state.search_response = search_insights_response(query.strip(), 10)
        st.session_state.search_scope = {"playlist_id": "", "playlist_type": ""}
        st.session_state.active_page = "search"
        st.query_params.clear()
        st.query_params["page"] = "search"
        st.rerun()
    recent = sorted((v for v in videos if v.get("status") == db.STATUS_DONE),
                    key=lambda v: v.get("processed_at") or v.get("added_at") or "", reverse=True)[:4]
    if recent:
        st.caption("Recently added")
        for video in recent:
            vid = video["video_id"]
            if not re.fullmatch(r"[\w-]{11}", vid):
                continue
            page_button(video.get("title") or "Untitled video", "library", video_id=vid)
    else:
        st.caption("Add your first video to start your library.")
def render_search_page() -> None:
    st.markdown(native_page_css(), unsafe_allow_html=True)
    render_native_nav("search")
    st.title("Search")
    st.caption("Find something you want to come back to.")

    playlists = dbcache.list_playlists()
    playlist_options = ["All playlists"] + [
        f"{p.get('name') or p['playlist_id']} ({p['playlist_id']})" for p in playlists
    ]
    id_by_label = {
        f"{p.get('name') or p['playlist_id']} ({p['playlist_id']})": p["playlist_id"]
        for p in playlists
    }

    with st.form("search_form"):
        query = st.text_input("Query", value=st.session_state.get("search_query", ""),
                              placeholder="Search your knowledge", label_visibility="collapsed")
        with st.expander("Filters"):
            col_a, col_b = st.columns(2)
            playlist_label = col_a.selectbox("Playlist", playlist_options)
            kind = col_b.selectbox("Type", ["Any", "General", "Podcast"])
        submitted = st.form_submit_button("Search", type="primary")

    if submitted:
        st.session_state.search_query = query
        playlist_id = None if playlist_label == "All playlists" else id_by_label.get(playlist_label)
        playlist_type = None
        if kind == "General":
            playlist_type = db.PLAYLIST_GENERAL
        elif kind == "Podcast":
            playlist_type = db.PLAYLIST_PODCAST
        with st.spinner("Searching your library…"):
            st.session_state.search_response = search_insights_response(
                query, 10, playlist_id=playlist_id, playlist_type=playlist_type
            )
        st.session_state.search_scope = {
            "playlist_id": playlist_id or "",
            "playlist_type": playlist_type or "",
        }

    response: SearchResponse | None = st.session_state.get("search_response")
    if response is None:
        return

    if response.status == "ok":
        st.caption(f"{len(response.hits)} results")
    elif response.status == "empty":
        st.info("No matches yet. Try a different topic or phrase.")
    elif response.status == "degraded":
        st.warning(" ; ".join(response.warnings) or "Degraded retrieval")
    else:
        st.error(" ; ".join(response.warnings) or "Search failed")

    collections = knowledge_store.list_collections()
    collection_names = {c["id"]: c["name"] for c in collections}

    for i, hit in enumerate(response.hits):
        st.subheader(hit.chunk_title or hit.video_title or "Insight")
        st.caption(
            f"{hit.video_title} · {hit.channel} · AI insight"
        )
        st.write(hit.chunk_text[:260] + ("…" if len(hit.chunk_text) > 260 else ""))
        if len(hit.chunk_text) > 260:
            with st.expander("Read insight"):
                st.write(hit.chunk_text)
        url = youtube_watch_url(hit.video_id, hit.timestamp_seconds)
        cols = st.columns(2)
        if url:
            cols[0].markdown(f"[Open source]({url})")
        if cols[1].button("Open video", key=f"open_{i}_{hit.source_id}"):
            st.session_state.selected_id = hit.video_id
            st.session_state.active_page = "library"
            st.query_params["page"] = "library"
            st.query_params["vid"] = hit.video_id
            st.rerun()
        with st.expander("Save to collection"):
            with st.form(f"save_hit_{i}"):
                note = st.text_input("Personal note", key=f"note_{i}")
                dest = st.selectbox(
                    "Collection",
                    ["(none)"] + list(collection_names.values()),
                    key=f"col_{i}",
                )
                if st.form_submit_button("Save"):
                    dest_id = next((cid for cid, n in collection_names.items() if n == dest), None)
                    knowledge_store.save_item(
                        kind=knowledge_store.KIND_INSIGHT,
                        title=hit.chunk_title or hit.video_title or "Insight",
                        body_snapshot=hit.chunk_text,
                        sources=[
                            {
                                "video_id": hit.video_id,
                                "title": hit.video_title,
                                "url": url,
                                "timestamp_seconds": hit.timestamp_seconds,
                                "source_kind": "insight",
                            }
                        ],
                        personal_note=note,
                        save_key=knowledge_store.insight_save_key(hit.video_id, hit.chunk_text),
                        collection_ids=[dest_id] if dest_id else None,
                    )
                    dbcache.invalidate()
                    st.toast("Saved")
        st.divider()

    if st.button("Ask the library"):
        st.session_state.chat_scope_type = "library"
        st.session_state.chat_scope_id = ""
        st.session_state.active_page = "chat"
        st.query_params["page"] = "chat"
        st.rerun()
def render_saved_page() -> None:
    st.markdown(native_page_css(), unsafe_allow_html=True)
    render_native_nav("saved")
    st.title("Saved")
    st.caption("The ideas you chose to keep.")
    collections = knowledge_store.list_collections()
    with st.expander("New collection"), st.form("new_collection"):
        st.subheader("New collection")
        name = st.text_input("Name", placeholder="e.g. Reading list")
        desc = st.text_input("Description")
        if st.form_submit_button("Create collection") and name.strip():
            knowledge_store.create_collection(name.strip(), desc)
            dbcache.invalidate()
            st.rerun()

    names = {c["id"]: c["name"] for c in collections}
    filter_id = None
    if collections:
        label = st.selectbox("Filter by collection", ["All"] + list(names.values()))
        if label != "All":
            filter_id = next(cid for cid, n in names.items() if n == label)

    items = knowledge_store.list_saved_items(collection_id=filter_id)
    if not items:
        st.info("Nothing saved yet.")
        return

    for item in items:
        st.markdown("---")
        st.subheader(item.get("title") or "Saved item")
        st.caption(f"{item.get('kind')} · updated {(item.get('updated_at') or '')[:10]}")
        body = item.get("body_snapshot") or ""
        st.write(body[:220] + ("…" if len(body) > 220 else ""))
        with st.expander("Read item"):
            st.write(body)
        with st.expander("Note and collections"), st.form(f"item_{item['id']}"):
            note = st.text_area("Personal note", value=item.get("personal_note") or "")
            membership = set(item.get("collection_ids") or [])
            chosen = st.multiselect(
                "Collections",
                options=list(names.values()),
                default=[names[cid] for cid in membership if cid in names],
            )
            col_a, col_b = st.columns(2)
            save_btn = col_a.form_submit_button("Update")
            export_btn = col_b.form_submit_button("Prepare download")
            if save_btn:
                knowledge_store.update_saved_item_note(item["id"], note)
                wanted = {cid for cid, n in names.items() if n in chosen}
                for cid in wanted - membership:
                    knowledge_store.add_item_to_collection(item["id"], cid)
                for cid in membership - wanted:
                    knowledge_store.remove_item_from_collection(item["id"], cid)
                dbcache.invalidate()
                st.toast("Updated")
            if export_btn:
                st.session_state.export_kind = "saved_item"
                st.session_state.export_id = item["id"]
                st.session_state.active_page = "export"
                st.query_params["page"] = "export"
                st.rerun()
def render_chat_page() -> None:
    st.markdown(native_page_css(), unsafe_allow_html=True)
    render_native_nav("chat")
    st.title("Ask your library")

    scope_type = st.session_state.get("chat_scope_type") or "library"
    scope_id = st.session_state.get("chat_scope_id") or ""
    if scope_type == "video" and scope_id:
        video = db.get_video(scope_id)
        st.caption(f"About {video.get('title') if video else scope_id}")
        stored = knowledge_store.get_transcript(scope_id)
        if not stored:
            st.warning("Transcript not saved yet.")
            if st.button("Acquire transcript"):
                from pipeline import fetch_transcript_data

                fetch_transcript_data(scope_id, persist=True, refresh=True)
                st.rerun()
        insights_only = st.checkbox("Answer from saved insights only", value=not bool(stored))
    else:
        st.caption("Answers drawn from your saved videos, with sources.")
        insights_only = False

    conversations = [
        c
        for c in knowledge_store.list_conversations()
        if c["scope_type"] == scope_type and (c.get("scope_id") or "") == (scope_id or "")
    ]
    labels = ["New conversation"] + [
        f"{c.get('title') or 'Conversation'} ({c['id'][:8]})" for c in conversations
    ]
    with st.expander("Past conversations"):
        chosen = st.selectbox("Conversation", labels)
    if chosen == "New conversation":
        conversation_id = st.session_state.get("chat_conversation_id")
        if not conversation_id:
            conversation_id = None
    else:
        conversation_id = next(
            c["id"] for c in conversations if c["id"][:8] in chosen
        )
        st.session_state.chat_conversation_id = conversation_id

    if conversation_id:
        convo = knowledge_store.get_conversation(conversation_id)
        if convo and (
            convo["scope_type"] != scope_type or (convo.get("scope_id") or "") != (scope_id or "")
        ):
            st.warning("This conversation keeps its original scope.")
        for msg in knowledge_store.list_messages(conversation_id):
            with st.chat_message(msg["role"] if msg["role"] in ("user", "assistant") else "assistant"):
                st.write(msg.get("content") or "")
                if msg.get("status") == "failed":
                    st.error("This attempt failed and can be retried.")
                if msg.get("status") == "uncertain":
                    st.warning("Save was interrupted. Retry to be sure.")
                try:
                    sources = json.loads(msg.get("sources_json") or "[]")
                except json.JSONDecodeError:
                    sources = []
                for src in sources:
                    url = safe_http_url(src.get("url") or "")
                    label = html.escape(src.get("title") or src.get("id") or "source")
                    kind = html.escape(src.get("label") or "")
                    if url:
                        st.markdown(f"- {kind}: [{label}]({url})")
                    else:
                        st.markdown(f"- {kind}: {label}")
                if msg.get("role") == "assistant" and msg.get("status") == "ok":
                    with st.form(f"save_ans_{msg['id']}"):
                        if st.form_submit_button("Save answer"):
                            knowledge_store.save_item(
                                kind=knowledge_store.KIND_ANSWER,
                                title=(msg.get("content") or "Answer")[:80],
                                body_snapshot=msg.get("content") or "",
                                sources=sources,
                                save_key=knowledge_store.answer_save_key(msg["id"]),
                            )
                            st.toast("Answer saved")

    with st.form("ask_form"):
        question = st.text_area("Question")
        submitted = st.form_submit_button("Ask")
    if submitted and question.strip():
        if not conversation_id:
            created = knowledge_store.create_conversation(
                title=question.strip()[:80],
                scope_type=scope_type,
                scope_id=scope_id,
            )
            conversation_id = created["id"]
            st.session_state.chat_conversation_id = conversation_id
        request_id = str(uuid.uuid4())
        ask(
            conversation_id=conversation_id,
            request_id=request_id,
            question=question.strip(),
            insights_only=insights_only,
        )
        st.rerun()

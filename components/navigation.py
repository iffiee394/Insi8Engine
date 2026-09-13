"""In-session navigation: never reload the browser document to change pages."""
from __future__ import annotations

import streamlit as st


def navigate(page: str, video_id: str = "") -> None:
    st.session_state.active_page = page
    params = {"page": page}
    if video_id:
        st.session_state.selected_id = video_id
        st.session_state.pop("library_video", None)
        st.session_state.pop("library_playlist", None)
        params["vid"] = video_id
    if page == "chat":
        st.session_state.chat_scope_type = "video" if video_id else "library"
        st.session_state.chat_scope_id = video_id
        st.session_state.chat_conversation_id = None
    # Update the URL through Streamlit, preserving the websocket and session.
    st.query_params.from_dict(params)


def page_button(label: str, page: str, *, video_id: str = "", key: str | None = None) -> None:
    st.button(label, key=key or f"open_{page}_{video_id}", on_click=navigate,
              args=(page, video_id), type="tertiary")

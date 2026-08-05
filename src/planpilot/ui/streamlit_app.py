import asyncio
import streamlit as st
import httpx
from planpilot.agent.agent import PlanPilotAgent
from planpilot.utils.config import get_settings
from planpilot.utils.preferences import (
    load_preferences,
    save_preferences,
    build_preference_context,
)

# ─────────────────── Page Config ───────────────────
st.set_page_config(
    page_title="PlanPilot - Personal AI Weekend Concierge",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────── Premium CSS ───────────────────
st.markdown(
    """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&family=Inter:wght@300;400;500;600&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Inter', sans-serif;
        background-color: #07030f;
        background-image:
            radial-gradient(ellipse at 15% 10%, rgba(139, 92, 246, 0.18) 0%, transparent 50%),
            radial-gradient(ellipse at 85% 85%, rgba(99, 102, 241, 0.15) 0%, transparent 50%),
            radial-gradient(ellipse at 50% 50%, rgba(16, 10, 30, 0.8) 0%, transparent 80%);
        color: #e2e8f0;
    }

    /* Header */
    .hero-title {
        font-family: 'Outfit', sans-serif;
        font-size: 3.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #ffffff 0%, #c4b5fd 50%, #818cf8 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -1px;
        line-height: 1.1;
        margin-bottom: 0;
    }

    .hero-subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 1rem;
        color: #94a3b8;
        font-weight: 400;
        margin-top: 6px;
        letter-spacing: 0.3px;
    }

    /* Sidebar */
    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(15, 10, 30, 0.97) 0%, rgba(20, 14, 40, 0.97) 100%) !important;
        border-right: 1px solid rgba(139, 92, 246, 0.2) !important;
        backdrop-filter: blur(20px);
    }

    /* Status badges */
    .badge-online {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 4px 12px; border-radius: 20px; font-size: 0.72rem; font-weight: 600;
        background: rgba(16, 185, 129, 0.12); color: #10b981;
        border: 1px solid rgba(16, 185, 129, 0.25);
        text-transform: uppercase; letter-spacing: 0.5px;
    }
    .badge-offline {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 4px 12px; border-radius: 20px; font-size: 0.72rem; font-weight: 600;
        background: rgba(239, 68, 68, 0.12); color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.25);
        text-transform: uppercase; letter-spacing: 0.5px;
    }

    /* Score ring */
    .score-ring {
        display: flex; flex-direction: column; align-items: center;
        padding: 16px;
        background: rgba(139, 92, 246, 0.08);
        border: 1px solid rgba(139, 92, 246, 0.2);
        border-radius: 16px;
        text-align: center;
    }
    .score-number {
        font-family: 'Outfit', sans-serif;
        font-size: 3.5rem; font-weight: 800;
        background: linear-gradient(135deg, #a78bfa, #818cf8);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text; line-height: 1;
    }
    .score-label { font-size: 0.85rem; color: #94a3b8; margin-top: 4px; }
    .score-title { font-size: 1rem; font-weight: 600; color: #c4b5fd; margin-top: 8px; }

    /* Plan cards */
    .plan-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(139, 92, 246, 0.15);
        border-radius: 12px; padding: 16px;
        transition: all 0.3s ease;
        margin-bottom: 12px;
    }
    .plan-card:hover {
        border-color: rgba(139, 92, 246, 0.4);
        background: rgba(139, 92, 246, 0.06);
        transform: translateY(-1px);
        box-shadow: 0 8px 24px rgba(139, 92, 246, 0.12);
    }

    /* Goal pills */
    .goal-pill {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 6px 16px; border-radius: 24px; font-size: 0.82rem; font-weight: 600;
        cursor: pointer; transition: all 0.2s ease;
        border: 1px solid rgba(139, 92, 246, 0.3);
        background: rgba(139, 92, 246, 0.1); color: #c4b5fd;
    }

    /* Buttons */
    .stButton > button {
        border-radius: 10px !important;
        font-family: 'Outfit', sans-serif !important;
        font-weight: 600 !important;
        transition: all 0.25s ease !important;
        letter-spacing: 0.2px !important;
    }
    .stButton > button:hover {
        border-color: #8b5cf6 !important;
        box-shadow: 0 0 16px rgba(139, 92, 246, 0.25) !important;
        transform: translateY(-1px) !important;
    }

    /* Chat messages */
    .stChatMessage {
        border-radius: 14px !important;
        border: 1px solid rgba(139, 92, 246, 0.08) !important;
        background: rgba(255,255,255,0.02) !important;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background: rgba(255,255,255,0.03);
        border-radius: 10px;
        padding: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        font-family: 'Outfit', sans-serif;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(139, 92, 246, 0.25) !important;
        color: #c4b5fd !important;
    }

    /* Tool trace */
    .tool-trace-item {
        display: flex; align-items: center; gap: 10px;
        padding: 8px 12px;
        background: rgba(255,255,255,0.03);
        border-left: 3px solid #8b5cf6;
        border-radius: 0 8px 8px 0;
        margin: 4px 0;
        font-size: 0.85rem;
        font-family: 'Inter', monospace;
    }

    /* Interest tags */
    .interest-tag {
        display: inline-block;
        padding: 4px 10px; border-radius: 16px; font-size: 0.78rem; font-weight: 500;
        background: rgba(139, 92, 246, 0.15); color: #c4b5fd;
        border: 1px solid rgba(139, 92, 246, 0.3); margin: 2px;
    }
    .dislike-tag {
        display: inline-block;
        padding: 4px 10px; border-radius: 16px; font-size: 0.78rem; font-weight: 500;
        background: rgba(239, 68, 68, 0.12); color: #fca5a5;
        border: 1px solid rgba(239, 68, 68, 0.25); margin: 2px;
    }

    /* Divider */
    .section-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(139,92,246,0.3), transparent);
        margin: 16px 0;
    }

    /* Metric cards */
    [data-testid="metric-container"] {
        background: rgba(139, 92, 246, 0.06);
        border: 1px solid rgba(139, 92, 246, 0.15);
        border-radius: 12px;
        padding: 12px 16px;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ─────────────────── Session State Init ───────────────────
def _init_state() -> None:
    if "agent" not in st.session_state:
        st.session_state.agent = PlanPilotAgent()
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "tool_trace" not in st.session_state:
        st.session_state.tool_trace = []  # list of {tool, args, time_ms}
    if "selected_goal" not in st.session_state:
        prefs = load_preferences()
        st.session_state.selected_goal = prefs.get("weekend_goal", "Explore")


_init_state()
settings = get_settings()

# ─────────────────── Sidebar ───────────────────
with st.sidebar:
    # Logo
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">'  
        '<span style="font-size:2rem">🧭</span>'
        '<span style="font-family:Outfit,sans-serif;font-size:1.4rem;font-weight:800;'
        'background:linear-gradient(135deg,#fff,#a78bfa);-webkit-background-clip:text;'
        '-webkit-text-fill-color:transparent;background-clip:text">PlanPilot</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="hero-subtitle" style="margin-bottom:12px">Personal AI Weekend Concierge</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # --- System Vitals ---
    st.markdown("**⚡ System Vitals**")
    provider = settings.llm_provider.lower().strip()

    if provider == "groq":
        if settings.groq_api_key:
            st.markdown('<span class="badge-online">🟢 Groq Cloud</span>', unsafe_allow_html=True)
            st.caption(f"Model: `{settings.groq_model}`")
        else:
            st.markdown('<span class="badge-offline">🔴 Groq Key Missing</span>', unsafe_allow_html=True)
    else:
        try:
            resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
            ollama_ok = resp.status_code == 200
        except Exception:
            ollama_ok = False
        if ollama_ok:
            st.markdown('<span class="badge-online">🟢 Ollama Active</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="badge-offline">🔴 Ollama Offline</span>', unsafe_allow_html=True)
        st.caption(f"Model: `{settings.ollama_model}`")

    serpapi_ok = bool(settings.serpapi_api_key and settings.serpapi_api_key.strip())
    if serpapi_ok:
        st.markdown('<span class="badge-online">🟢 SerpAPI Active</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge-offline">🟡 SerpAPI not set</span>', unsafe_allow_html=True)

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # --- Weekend Goal Selector ---
    st.markdown("**🎯 Weekend Goal**")
    goal_options = {
        "Relax": "🛋️ Relax",
        "Learn": "📚 Learn",
        "Explore": "🗺️ Explore",
        "Socialize": "🎉 Socialize",
    }
    selected_goal = st.radio(
        "What's your vibe this weekend?",
        options=list(goal_options.keys()),
        format_func=lambda x: goal_options[x],
        index=list(goal_options.keys()).index(st.session_state.selected_goal)
        if st.session_state.selected_goal in goal_options
        else 2,
        key="goal_radio",
        label_visibility="collapsed",
    )
    if selected_goal != st.session_state.selected_goal:
        st.session_state.selected_goal = selected_goal
        from planpilot.utils.preferences import set_preference
        set_preference("weekend_goal", selected_goal)

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # --- Model Config ---
    with st.expander("⚙️ Model Configuration", expanded=False):
        provider_select = st.selectbox(
            "LLM Provider:", options=["Ollama", "Groq"], index=0 if provider == "ollama" else 1
        )
        if provider_select == "Groq":
            groq_model_input = st.text_input("Groq Model:", value=settings.groq_model)
            groq_key_input = st.text_input("Groq API Key:", value=settings.groq_api_key or "", type="password")
            if st.button("Apply Groq Settings"):
                settings.llm_provider = "groq"
                settings.groq_model = groq_model_input
                settings.groq_api_key = groq_key_input
                st.session_state.agent.reset()
                st.success("Switched to Groq!")
                st.rerun()
        else:
            ollama_model_input = st.text_input("Ollama Model:", value=settings.ollama_model)
            if st.button("Apply Ollama Settings"):
                settings.llm_provider = "ollama"
                settings.ollama_model = ollama_model_input
                st.session_state.agent.reset()
                st.success("Switched to Ollama!")
                st.rerun()

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    if st.button("🗑️ Clear Chat History", use_container_width=True):
        st.session_state.agent.reset()
        st.session_state.chat_history = []
        st.session_state.tool_trace = []
        st.success("History cleared.")
        st.rerun()


# ─────────────────── Main Layout ───────────────────
col_main, col_panel = st.columns([3, 1], gap="large")

with col_main:
    # Hero header
    st.markdown('<h1 class="hero-title">🧭 PlanPilot</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="hero-subtitle">Your Personal AI Weekend Concierge — powered by MCP, Ollama/Groq, and real-world data</p>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # Tabs: Chat | Preferences | Tool Trace
    tab_chat, tab_prefs, tab_trace = st.tabs(["💬 Chat", "👤 My Profile", "🔍 Tool Trace"])

    # ─── Chat Tab ───
    with tab_chat:
        # Display current goal banner
        goal_emoji = {"Relax": "🛋️", "Learn": "📚", "Explore": "🗺️", "Socialize": "🎉"}
        st.info(
            f"{goal_emoji.get(selected_goal, '🎯')} **Weekend Goal: {selected_goal}** — "
            "The agent will tailor all recommendations to match your vibe."
        )

        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input(
            f"Ask your Weekend Concierge... (Goal: {selected_goal})"
        ):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                import time
                status_box = st.status("Planning your weekend...", expanded=True)
                trace_items: list[dict] = []

                async def ui_callback(msg: str) -> None:
                    print(f"[PlanPilot Log] {msg}", flush=True)
                    if "Calling tool '" in msg:
                        tool_name = msg.split("'")[1] if "'" in msg else "tool"
                        args_part = msg.split("args ")[-1] if "args " in msg else "{}"
                        t_start = time.monotonic()
                        status_box.write(f"⚙️ **Tool Call:** `{tool_name}` — {args_part}")
                        trace_items.append({"tool": tool_name, "args": args_part, "started": t_start})
                    elif "Received output" in msg:
                        tool_name = msg.replace("Received output from '", "").replace("'", "")
                        # Find and complete the trace item
                        for item in reversed(trace_items):
                            if item["tool"] == tool_name and "duration_ms" not in item:
                                item["duration_ms"] = int((time.monotonic() - item["started"]) * 1000)
                                break
                        status_box.write(f"✅ **Output received:** `{tool_name}`")
                    else:
                        status_box.update(label=msg)

                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        response = loop.run_until_complete(
                            st.session_state.agent.run_query(
                                prompt,
                                status_callback=ui_callback,
                                goal=st.session_state.selected_goal,
                            )
                        )
                    finally:
                        loop.close()

                    status_box.update(label="Plan compiled! ✨", state="complete", expanded=False)

                    # Save trace
                    for item in trace_items:
                        if "duration_ms" not in item:
                            item["duration_ms"] = 0
                    st.session_state.tool_trace.extend(trace_items)

                    st.markdown(response)
                    st.session_state.chat_history.append({"role": "assistant", "content": response})

                except BaseException as e:
                    # Handles both regular exceptions and Python 3.11+ BaseExceptionGroup
                    # (raised by anyio TaskGroup used inside the MCP stdio_client)
                    if hasattr(e, "exceptions"):
                        errs = "; ".join(str(sub) for sub in e.exceptions)  # type: ignore[attr-defined]
                    else:
                        errs = str(e)
                    status_box.update(label="Something went wrong!", state="error", expanded=True)
                    st.error(f"Error: {errs}")

    # ─── Preferences Tab ───
    with tab_prefs:
        st.markdown("### 👤 Your Profile")
        st.caption("Preferences are saved automatically and used to personalise every recommendation.")

        prefs = load_preferences()

        col_a, col_b = st.columns(2)
        with col_a:
            home_city = st.text_input(
                "🏙️ Home City",
                value=prefs.get("home_city", ""),
                placeholder="e.g. Indore",
                key="pref_city",
            )
            budget_opts = ["any", "budget", "mid-range", "premium"]
            budget = st.selectbox(
                "💰 Budget Preference",
                options=budget_opts,
                index=budget_opts.index(prefs.get("preferred_budget", "any")),
                key="pref_budget",
            )
            indoor = st.checkbox(
                "🏠 Prefer Indoor Activities",
                value=prefs.get("indoor_preference", False),
                key="pref_indoor",
            )

        with col_b:
            interests_str = st.text_area(
                "❤️ Interests (one per line)",
                value="\n".join(prefs.get("interests", [])),
                placeholder="rock concerts\nsci-fi books\nhiking\nfood festivals",
                height=100,
                key="pref_interests",
            )
            dislikes_str = st.text_area(
                "🚫 Dislikes (one per line)",
                value="\n".join(prefs.get("dislikes", [])),
                placeholder="horror movies\ncrowded malls",
                height=80,
                key="pref_dislikes",
            )

        notes = st.text_input(
            "📝 Custom Notes",
            value=prefs.get("custom_notes", ""),
            placeholder="e.g. Vegetarian, prefer morning events",
            key="pref_notes",
        )

        if st.button("💾 Save Profile", type="primary", use_container_width=True):
            new_prefs = {
                "home_city": home_city.strip(),
                "interests": [i.strip() for i in interests_str.strip().splitlines() if i.strip()],
                "dislikes": [d.strip() for d in dislikes_str.strip().splitlines() if d.strip()],
                "preferred_budget": budget,
                "weekend_goal": st.session_state.selected_goal,
                "indoor_preference": indoor,
                "custom_notes": notes.strip(),
            }
            save_preferences(new_prefs)
            st.success("✅ Profile saved! Preferences will apply to your next query.")
            # Reset agent so new context is injected fresh
            st.session_state.agent.reset()
            st.rerun()

        # Preview
        st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
        st.markdown("**📋 Current Profile Preview**")
        context_str = build_preference_context(prefs)
        if context_str:
            st.code(context_str, language=None)
        else:
            st.caption("No preferences set yet. Fill in the form above to personalise PlanPilot!")

    # ─── Tool Trace Tab ───
    with tab_trace:
        st.markdown("### 🔍 Tool Usage Trace")
        st.caption("Real-time log of every MCP tool call made in this session.")

        if not st.session_state.tool_trace:
            st.info("No tool calls yet. Ask the concierge something to see the trace!")
        else:
            total_calls = len(st.session_state.tool_trace)
            total_ms = sum(t.get("duration_ms", 0) for t in st.session_state.tool_trace)

            m1, m2 = st.columns(2)
            m1.metric("Total Tool Calls", total_calls)
            m2.metric("Total Latency", f"{total_ms} ms")

            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
            for i, trace in enumerate(reversed(st.session_state.tool_trace), 1):
                dur = trace.get("duration_ms", 0)
                st.markdown(
                    f'<div class="tool-trace-item">'
                    f'<span style="color:#a78bfa;font-weight:600">#{i}</span> '
                    f'<span style="color:#c4b5fd">🔧 {trace["tool"]}</span> '
                    f'<span style="color:#64748b">{trace["args"][:60]}...</span> '
                    f'<span style="color:#10b981;margin-left:auto">{dur}ms</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            if st.button("🗑️ Clear Trace"):
                st.session_state.tool_trace = []
                st.rerun()


# ─────────────────── Right Panel: Weekend Scorecard ───────────────────
with col_panel:
    st.markdown("### 📊 Weekend Scorecard")
    prefs = load_preferences()
    score_city = prefs.get("home_city", "").strip()

    if score_city:
        if st.button("🔄 Refresh Score", use_container_width=True, key="refresh_score"):
            st.session_state["score_data"] = None  # force refresh

        score_data = st.session_state.get("score_data")

        if score_data is None:
            with st.spinner("Analysing your weekend..."):
                try:
                    from planpilot.tools.services import get_weather_data, discover_events_data, compute_weekend_score

                    async def _fetch_score():
                        import asyncio as _aio
                        weather, events = await _aio.gather(
                            get_weather_data(score_city),
                            discover_events_data(score_city),
                        )
                        return compute_weekend_score(weather, events, prefs), weather, events

                    _loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(_loop)
                    try:
                        score_data, _weather, _events = _loop.run_until_complete(_fetch_score())
                    finally:
                        _loop.close()
                    score_data["_weather"] = _weather
                    score_data["_events"] = _events
                    st.session_state["score_data"] = score_data
                except BaseException as e:
                    if hasattr(e, "exceptions"):
                        errs = "; ".join(str(sub) for sub in e.exceptions)  # type: ignore[attr-defined]
                    else:
                        errs = str(e)
                    st.error(f"Score error: {errs}")
                    score_data = None

        if score_data:
            score = score_data.get("score", 0)
            label = score_data.get("label", "")
            weather_sum = score_data.get("weather_summary", "")
            tips = score_data.get("tips", [])
            n_events = score_data.get("events_found", 0)
            bonus = score_data.get("preference_bonus", 0)

            # Score ring
            score_color = "#10b981" if score >= 70 else "#f59e0b" if score >= 40 else "#ef4444"
            st.markdown(
                f'<div class="score-ring">'
                f'<div class="score-number" style="color:{score_color};-webkit-text-fill-color:{score_color}">{score}</div>'
                f'<div class="score-label">/100</div>'
                f'<div class="score-title">{label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

            # Metrics
            col_s1, col_s2 = st.columns(2)
            col_s1.metric("Events Found", n_events)
            col_s2.metric("Pref Bonus", f"+{bonus}")

            st.caption(f"📍 {score_city}")
            st.caption(weather_sum)

            if tips:
                st.markdown("**💡 Tips**")
                for tip in tips:
                    st.markdown(f"- {tip}")

            # Top events preview
            _events = score_data.get("_events", [])
            valid_ev = [e for e in _events if "Notice" not in e.get("source", "") and "Warning" not in e.get("source", "")]
            if valid_ev:
                st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
                st.markdown("**🎟️ Top Events**")
                for ev in valid_ev[:3]:
                    with st.expander(ev.get("source", "Event")[:35]):
                        st.caption(ev.get("summary", ""))

    else:
        st.info(
            "👤 Set your **Home City** in the **My Profile** tab to see your personalised Weekend Score here!"
        )
        st.markdown(
            """**The scorecard shows:**
- 🌤️ Weather summary
- 🎟️ Events available
- ⭐ Preference match bonus
- 💡 Smart weekend tips"""
        )

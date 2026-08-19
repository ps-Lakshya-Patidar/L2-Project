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


def _run_async(coro):
    """Safely run an async coroutine in Streamlit's script runner thread.

    Prevents 'RuntimeError: Event loop is closed' when Streamlit's script thread finishes.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            if pending:
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        finally:
            loop.close()
            # Restore a fresh, open loop for the current thread so Streamlit's completion handlers don't crash
            try:
                asyncio.set_event_loop(asyncio.new_event_loop())
            except Exception:
                pass


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

    if provider == "openrouter":
        if settings.openrouter_api_key:
            st.markdown('<span class="badge-online">🟢 OpenRouter Active</span>', unsafe_allow_html=True)
            st.caption(f"Model: `{settings.openrouter_model}`")
        else:
            st.markdown('<span class="badge-offline">🔴 OpenRouter Key Missing</span>', unsafe_allow_html=True)
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

    # --- Travel Goal Selector ---
    st.markdown("**✈️ Travel Vibe Goal**")
    goal_options = {
        "Budget Tour": "💰 Budget Tour",
        "Explore": "🗺️ Sightseeing & Heritage",
        "Relax": "🛋️ Leisure & Staycation",
        "Adventure": "🏔️ Outdoor & Adventure",
    }
    selected_goal = st.radio(
        "What's your vibe for this trip?",
        options=list(goal_options.keys()),
        format_func=lambda x: goal_options[x],
        index=list(goal_options.keys()).index(st.session_state.selected_goal)
        if st.session_state.selected_goal in goal_options
        else 1,
        key="goal_radio",
        label_visibility="collapsed",
    )
    if selected_goal != st.session_state.selected_goal:
        st.session_state.selected_goal = selected_goal
        from planpilot.utils.preferences import set_preference
        set_preference("weekend_goal", selected_goal)

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # --- Model Config ---
    with st.expander("⚙️ Model Configuration", expanded=True):
        provider_options = ["OpenRouter", "Ollama"]
        current_idx = 0 if provider == "openrouter" else 1

        provider_select = st.selectbox(
            "LLM Provider:", options=provider_options, index=current_idx
        )
        target_provider = provider_select.lower()
        if target_provider != settings.llm_provider:
            settings.llm_provider = target_provider
            st.session_state.agent.reset()
            st.rerun()

        if provider_select == "OpenRouter":
            openrouter_free_models = [
                "openrouter/free",
                "openai/gpt-oss-20b:free",
                "nvidia/nemotron-3-nano-30b-a3b:free",
                "google/gemma-4-31b-it:free",
                "google/gemma-4-26b-a4b-it:free",
                "nvidia/nemotron-3.5-lightning:free",
                "nvidia/nemotron-3-super-120b-a12b:free",
                "nvidia/nemotron-3-ultra-550b-a55b:free",
                "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                "nvidia/nemotron-nano-12b-v2-vl:free",
                "nvidia/nemotron-nano-9b-v2:free",
                "z-ai/glm-5.2:free",
                "cohere/north-mini-code:free",
                "dots-studio/dots-3-note-preview:free",
                "poolside/laguna-s-2.1:free",
                "poolside/laguna-xs-2.1:free",
                "meta-llama/llama-3.3-70b-instruct:free",
                "meta-llama/llama-3.1-8b-instruct:free",
                "deepseek/deepseek-r1:free",
                "deepseek/deepseek-chat:free",
                "mistralai/mistral-7b-instruct:free",
                "qwen/qwen-2.5-72b-instruct:free",
                "Custom Model..."
            ]
            curr_or = settings.openrouter_model
            if curr_or not in openrouter_free_models:
                openrouter_free_models.insert(0, curr_or)

            selected_or = st.selectbox(
                "OpenRouter Free Model:",
                options=openrouter_free_models,
                index=openrouter_free_models.index(curr_or) if curr_or in openrouter_free_models else 0
            )

            if selected_or == "Custom Model...":
                or_model_input = st.text_input("Enter Custom OpenRouter Model:", value=curr_or)
            else:
                or_model_input = selected_or

            or_key_input = st.text_input(
                "OpenRouter API Key:",
                value=settings.openrouter_api_key or "",
                type="password",
                placeholder="sk-or-v1-...",
            )

            if (or_model_input != settings.openrouter_model) or (or_key_input and or_key_input != settings.openrouter_api_key):
                if st.button("Apply OpenRouter Settings", use_container_width=True):
                    settings.openrouter_model = or_model_input
                    if or_key_input:
                        settings.openrouter_api_key = or_key_input
                    st.session_state.agent.reset()
                    st.success("OpenRouter settings applied!")
                    st.rerun()
        else:
            # Fetch local Ollama models dynamically
            available_models = []
            try:
                resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
                if resp.status_code == 200:
                    models_data = resp.json().get("models", [])
                    available_models = [m["name"] for m in models_data if "embed" not in m["name"].lower()]
            except Exception:
                pass
            
            # Prepopulate defaults if Ollama is not accessible or doesn't have them
            defaults = ["llama3.2:3b"]
            for d in defaults:
                if d not in available_models:
                    available_models.append(d)
            
            # Ensure the current model is present
            curr_model = settings.ollama_model
            if curr_model not in available_models:
                available_models.insert(0, curr_model)
            
            available_models.append("Custom Override...")
            
            selected_model = st.selectbox(
                "Ollama Model:",
                options=available_models,
                index=available_models.index(curr_model) if curr_model in available_models else 0
            )
            
            if selected_model == "Custom Override...":
                ollama_model_input = st.text_input("Enter Model Name:", value=curr_model)
            else:
                ollama_model_input = selected_model

            if ollama_model_input != settings.ollama_model:
                settings.ollama_model = ollama_model_input
                st.session_state.agent.reset()
                st.rerun()

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    if st.button("🗑️ Clear Chat History", use_container_width=True):
        st.session_state.agent.reset()
        st.session_state.chat_history = []
        st.session_state.tool_trace = []
        st.success("History cleared.")
        st.rerun()


# ─────────────────── Main Layout ───────────────────
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

        def estimate_cost(provider: str, model: str, input_tok: int, output_tok: int) -> str:
            prov = provider.lower().strip()
            mod = model.lower().strip()
            if prov == "ollama":
                return "$0.00 (Local)"
            if prov == "openrouter":
                if ":free" in mod or mod == "openrouter/free":
                    return "$0.00 (Free Tier)"
                in_rate = 0.10
                out_rate = 0.20
                cost = (input_tok * (in_rate / 1_000_000)) + (output_tok * (out_rate / 1_000_000))
                return f"${cost:.6f}"
            if prov == "gemini":
                # Google Gemini 3.6 / 3.7 / 2.5 Flash Free Tier
                in_rate = 0.075
                out_rate = 0.30
                cost = (input_tok * (in_rate / 1_000_000)) + (output_tok * (out_rate / 1_000_000))
                return f"${cost:.6f} (Free Tier)"
            # Default Groq pricing per million tokens
            in_rate = 0.05
            out_rate = 0.08
            if "70b" in mod:
                in_rate = 0.59
                out_rate = 0.79
            elif "mixtral" in mod:
                in_rate = 0.24
                out_rate = 0.24
            cost = (input_tok * (in_rate / 1_000_000)) + (output_tok * (out_rate / 1_000_000))
            return f"${cost:.6f}"

        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message.get("role") == "assistant" and message.get("metrics"):
                    m = message["metrics"]
                    cost_str = estimate_cost(m['provider'], m['model'], m['input_tokens'], m['output_tokens'])
                    st.markdown(
                        f"""
                        <div style="background-color: rgba(139, 92, 246, 0.05); border: 1px solid rgba(139, 92, 246, 0.15); border-radius: 8px; padding: 10px; margin-top: 10px; font-size: 0.85rem;">
                            <div style="font-weight: 600; color: #a78bfa; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
                                📊 Evaluation Metrics
                            </div>
                            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px;">
                                <div><b>LLM:</b> <code>{m['provider']}/{m['model']}</code></div>
                                <div><b>Latency:</b> <code>{m['latency_sec']}s</code></div>
                                <div><b>Cost:</b> <code>{cost_str}</code></div>
                                <div><b>LLM Steps:</b> <code>{m['llm_calls']}</code></div>
                                <div><b>Tool Calls:</b> <code>{m['tool_calls']}</code></div>
                                <div><b>Input Tokens:</b> <code>{m['input_tokens']}</code></div>
                                <div><b>Output Tokens:</b> <code>{m['output_tokens']}</code></div>
                                <div><b>Total Tokens:</b> <code>{m['total_tokens']}</code></div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

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
                    if msg.startswith("TOOL_TRACE:start:"):
                        parts = msg.split(":", 3)
                        tool_name = parts[2] if len(parts) > 2 else "tool"
                        args_part = parts[3] if len(parts) > 3 else "{}"
                        t_start = time.monotonic()
                        trace_items.append({"tool": tool_name, "args": args_part, "started": t_start})
                        try:
                            status_box.write(f"⚙️ **Tool Call:** `{tool_name}`")
                        except BaseException:
                            pass
                    elif msg.startswith("TOOL_TRACE:end:"):
                        parts = msg.split(":", 3)
                        tool_name = parts[2] if len(parts) > 2 else "tool"
                        source = parts[3] if len(parts) > 3 else "live"
                        for item in reversed(trace_items):
                            if item["tool"] == tool_name and "duration_ms" not in item:
                                item["duration_ms"] = int((time.monotonic() - item["started"]) * 1000)
                                item["source"] = source
                                break
                        try:
                            icon = "⚡" if source == "cache" else "✅"
                            status_box.write(f"{icon} **Output received:** `{tool_name}` ({source})")
                        except BaseException:
                            pass
                    else:
                        try:
                            status_box.update(label=msg)
                        except BaseException:
                            pass

                try:
                    response = _run_async(
                        st.session_state.agent.run_query(
                            prompt,
                            status_callback=ui_callback,
                            goal=st.session_state.selected_goal,
                        )
                    )

                    status_box.update(label="Plan compiled! ✨", state="complete", expanded=False)

                    # Save trace
                    for item in trace_items:
                        if "duration_ms" not in item:
                            item["duration_ms"] = 0
                    st.session_state.tool_trace.extend(trace_items)

                    st.markdown(response)
                    
                    metrics_to_save = getattr(st.session_state.agent, "last_metrics", None)
                    if metrics_to_save:
                        # Create a local copy to ensure thread safety / persistence
                        metrics_to_save = dict(metrics_to_save)
                    
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": response,
                        "metrics": metrics_to_save
                    })
                    
                    if metrics_to_save:
                        cost_val_str = estimate_cost(
                            metrics_to_save['provider'],
                            metrics_to_save['model'],
                            metrics_to_save['input_tokens'],
                            metrics_to_save['output_tokens']
                        )
                        st.markdown(
                            f"""
                            <div style="background-color: rgba(139, 92, 246, 0.05); border: 1px solid rgba(139, 92, 246, 0.15); border-radius: 8px; padding: 10px; margin-top: 10px; font-size: 0.85rem;">
                                <div style="font-weight: 600; color: #a78bfa; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
                                    📊 Evaluation Metrics
                                </div>
                                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px;">
                                    <div><b>LLM:</b> <code>{metrics_to_save['provider']}/{metrics_to_save['model']}</code></div>
                                    <div><b>Latency:</b> <code>{metrics_to_save['latency_sec']}s</code></div>
                                    <div><b>Cost:</b> <code>{cost_val_str}</code></div>
                                    <div><b>LLM Steps:</b> <code>{metrics_to_save['llm_calls']}</code></div>
                                    <div><b>Tool Calls:</b> <code>{metrics_to_save['tool_calls']}</code></div>
                                    <div><b>Input Tokens:</b> <code>{metrics_to_save['input_tokens']}</code></div>
                                    <div><b>Output Tokens:</b> <code>{metrics_to_save['output_tokens']}</code></div>
                                    <div><b>Total Tokens:</b> <code>{metrics_to_save['total_tokens']}</code></div>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )

                except BaseException as e:
                    # Handles both regular exceptions and Python 3.11+ BaseExceptionGroup
                    # (raised by anyio TaskGroup used inside the MCP stdio_client)
                    # Save any trace items collected before the crash
                    for item in trace_items:
                        if "duration_ms" not in item:
                            item["duration_ms"] = 0
                    st.session_state.tool_trace.extend(trace_items)
                    if hasattr(e, "exceptions"):
                        errs = "; ".join(str(sub) for sub in e.exceptions)  # type: ignore[attr-defined]
                    else:
                        errs = str(e)
                    try:
                        status_box.update(label="Something went wrong!", state="error", expanded=True)
                        st.error(f"Error: {errs}")
                    except BaseException:
                        pass

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


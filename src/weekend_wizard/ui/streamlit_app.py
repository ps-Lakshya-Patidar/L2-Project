import asyncio
import streamlit as st
import httpx
from weekend_wizard.agent.agent import WeekendWizardAgent
from weekend_wizard.utils.config import get_settings

# Page config and premium styling
st.set_page_config(
    page_title="🧙 Weekend Wizard", page_icon="🧙", layout="wide", initial_sidebar_state="expanded"
)

# Inject custom premium CSS for glowing purple borders, glassmorphism, and Outfit font
st.markdown(
    """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Inter:wght@300;400;500;600&display=swap');
    
    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Inter', sans-serif;
        background-color: #0c0914;
        background-image: radial-gradient(circle at 10% 20%, rgba(139, 92, 246, 0.15) 0%, transparent 40%),
                          radial-gradient(circle at 90% 80%, rgba(99, 102, 241, 0.15) 0%, transparent 40%);
        color: #e2e8f0;
    }
    
    /* Header title */
    .header-title {
        font-family: 'Outfit', sans-serif;
        font-size: 2.8rem;
        font-weight: 700;
        background: linear-gradient(135deg, #ffffff 30%, #a78bfa 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 5px;
    }
    
    /* Glassmorphic cards */
    div[data-testid="stSidebar"] {
        background-color: rgba(20, 16, 35, 0.6) !important;
        border-right: 1px solid rgba(139, 92, 246, 0.15) !important;
        backdrop-filter: blur(15px);
    }
    
    /* Status indicators */
    .status-badge {
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        display: inline-block;
    }
    
    .status-online {
        background-color: rgba(16, 185, 129, 0.15);
        color: #10b981;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    
    .status-offline {
        background-color: rgba(239, 68, 68, 0.15);
        color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }
    
    /* Button styles */
    .stButton>button {
        border-radius: 8px !important;
        font-family: 'Outfit', sans-serif !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
    }
    
    .stButton>button:hover {
        border-color: #8b5cf6 !important;
        color: #8b5cf6 !important;
        box-shadow: 0 0 10px rgba(139, 92, 246, 0.2);
    }
</style>
""",
    unsafe_allow_html=True,
)

# Initialize Session State
if "agent" not in st.session_state:
    st.session_state.agent = WeekendWizardAgent()
    st.session_state.chat_history = []

settings = get_settings()

# Sidebar Panel
with st.sidebar:
    st.markdown(
        '<div class="logo"><span style="font-size:2.2rem">🧙</span><span class="header-title" style="font-size:1.6rem; vertical-align:middle; margin-left:10px">Weekend Wizard</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # Check Connection Statuses
    st.subheader("System Vitals")
    provider = settings.llm_provider.lower().strip()

    if provider == "groq":
        if settings.groq_api_key:
            st.markdown(
                '<span class="status-badge status-online">🟢 Groq Active</span>',
                unsafe_allow_html=True,
            )
            st.info(f"**Provider:** `Groq Cloud`\n\n**Active Model:** `{settings.groq_model}`")
        else:
            st.markdown(
                '<span class="status-badge status-offline">🔴 Groq Key Missing</span>',
                unsafe_allow_html=True,
            )
            st.warning("Please supply a valid Groq API key in Settings below.")
    else:
        try:
            resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
            connected = resp.status_code == 200
        except Exception:
            connected = False

        if connected:
            st.markdown(
                '<span class="status-badge status-online">🟢 Ollama Connected</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<span class="status-badge status-offline">🔴 Ollama Offline</span>',
                unsafe_allow_html=True,
            )

        st.info(f"**Provider:** `Local Ollama`\n\n**Active Model:** `{settings.ollama_model}`")

    # Model Selector settings
    st.subheader("Model Configuration")

    provider_select = st.selectbox(
        "LLM Provider:", options=["Ollama", "Groq"], index=0 if provider == "ollama" else 1
    )

    if provider_select == "Groq":
        groq_model_input = st.text_input("Groq Model Name:", value=settings.groq_model)
        groq_key_input = st.text_input(
            "Groq API Key:", value=settings.groq_api_key or "", type="password"
        )

        if st.button("Apply Groq Changes"):
            settings.llm_provider = "groq"
            settings.groq_model = groq_model_input
            settings.groq_api_key = groq_key_input
            st.session_state.agent.reset()
            st.success("Switched provider to Groq!")
            st.rerun()
    else:
        ollama_model_input = st.text_input("Ollama Model Name:", value=settings.ollama_model)
        if st.button("Apply Ollama Changes"):
            settings.llm_provider = "ollama"
            settings.ollama_model = ollama_model_input
            st.session_state.agent.reset()
            st.success("Switched provider to Ollama!")
            st.rerun()

    st.markdown("---")
    if st.button("🗑️ Reset Spell History", use_container_width=True):
        st.session_state.agent.reset()
        st.session_state.chat_history = []
        st.success("Conversation history cleared.")
        st.rerun()

# Main Header
st.markdown('<h1 class="header-title">🧙 Weekend Wizard Portal</h1>', unsafe_allow_html=True)
st.write(
    "A local AI assistant driven by Model Context Protocol (MCP) tool server to check weather, books, and discover local events."
)

# Display Chat History
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User Chat Input
if prompt := st.chat_input("Whisper your query here (e.g. What is the weather in Delhi?)..."):
    # Render user query
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.chat_history.append({"role": "user", "content": prompt})

    # Assistant container
    with st.chat_message("assistant"):
        # Live status step tracer
        status_box = st.status("Conjuring magic...", expanded=True)

        async def ui_status_callback(msg: str) -> None:
            if "Calling tool" in msg:
                status_box.write(f"⚙️ **MCP Tool Call:** {msg.replace('Calling tool ', '')}")
            elif "Received output" in msg:
                status_box.write(
                    f"✔ **Tool Output Received:** {msg.replace('Received output from ', '')}"
                )
            else:
                status_box.update(label=msg)

        # Running query asynchronously
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            response = loop.run_until_complete(
                st.session_state.agent.run_query(prompt, status_callback=ui_status_callback)
            )

            # Close/complete the status box
            status_box.update(label="Response conjured!", state="complete", expanded=False)

            # Print final response
            st.markdown(response)
            st.session_state.chat_history.append({"role": "assistant", "content": response})

        except Exception as e:
            status_box.update(label="Spell Failed!", state="error", expanded=True)
            st.error(f"Execution Error: {str(e)}")

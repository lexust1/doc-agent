"""
Streamlit UI for the Doc assistant.
Caches heavy resources and stores chat history in a sidebar.
Supports both a fast simple answer mode and an advanced agentic mode
with question decomposition, iterative retrieval, and faithfulness checks.
"""

import logging
import re

import streamlit as st

from doc_agent.configs.settings import settings
from doc_agent.indexing.embedder import Embedder
from doc_agent.retrieval.hybrid_searcher import HybridSearcher
from doc_agent.agents.answer_generator import AnswerGeneratorAgent
from doc_agent.agents.agentic_answer_agent import AgenticAnswerAgent
from doc_agent.utils.logger import setup_logger

# ---------------------------------------------------------------------------
# 1. Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Doc Agent",
    page_icon="⚡",
    layout="wide",                # use full width for better readability
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# 2. Custom CSS (Links and Neutralized Code Blocks)
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* Style citation links as superscript badges.
       These are generated dynamically when [N] is converted to a link. */
    a[href^="#source-"] {
        color: var(--primary-color);
        text-decoration: none;
        font-weight: bold;
        vertical-align: super;
        font-size: 0.85em;
        padding: 0 2px;
    }
    a[href^="#source-"]:hover {
        text-decoration: underline;
    }
    
    /* Override Streamlit's default green code styling.
       We want citations to look neutral, not like code blocks. */
    code {
        color: #E0E0E0 !important;
        background-color: #2B2B2B !important;
        border-radius: 4px;
        padding: 2px 4px;
        font-size: 0.9em;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 3. Load heavy resources once and cache them
#    Streamlit re‑runs this script on every user interaction; caching
#    prevents re‑loading the model, searcher, and prompt each time.
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def load_embedder() -> Embedder:
    """Load the BGE‑M3 ONNX embedder once per session."""
    # Suppress verbose logging from the embedder during UI startup
    setup_logger(name="", level=logging.WARNING)
    return Embedder()

@st.cache_resource(show_spinner=False)
def load_searcher(_embedder: Embedder) -> HybridSearcher:
    """Create the hybrid searcher, depending on the cached embedder."""
    return HybridSearcher(_embedder)

@st.cache_resource(show_spinner=False)
def load_agent(_searcher: HybridSearcher) -> AnswerGeneratorAgent:
    """Create the simple answer generator (fast, single‑pass retrieval)."""
    return AnswerGeneratorAgent(_searcher)

@st.cache_resource(show_spinner=False)
def load_agentic_agent(_searcher: HybridSearcher) -> AgenticAnswerAgent:
    """Create the advanced agentic answer agent (decompose + judge + verify).
    
    This agent wraps the simple generator and adds an iterative reasoning
    loop.  It is more expensive in LLM calls but produces more reliable
    answers for complex, multi‑hop regulatory questions.
    """
    # The agentic agent needs an answer generator to produce the final text
    answer_gen = AnswerGeneratorAgent(_searcher)
    return AgenticAnswerAgent(_searcher, answer_gen)

@st.cache_data(show_spinner=False)
def load_system_prompt() -> str:
    """Load the answer generation prompt from disk (cached as data)."""
    path = settings.PROMPTS_DIR / "answer_generation.md"
    return path.read_text(encoding="utf-8")

# Instantiate all cached resources. The underscore prefixes on parameters
# tell Streamlit not to hash those objects; only their identity matters.
embedder = load_embedder()
searcher = load_searcher(embedder)
agent = load_agent(searcher)
agentic_agent = load_agentic_agent(searcher)
system_prompt = load_system_prompt()

# ---------------------------------------------------------------------------
# 4. Session state initialisation
#    These variables survive script re‑runs and keep the UI interactive.
# ---------------------------------------------------------------------------
if "history" not in st.session_state:
    st.session_state.history = []          # list of Q&A entries
if "selected_index" not in st.session_state:
    st.session_state.selected_index = None # index of the currently viewed conversation

# ---------------------------------------------------------------------------
# 5. Sidebar – Chat History
# ---------------------------------------------------------------------------
st.sidebar.title("⚡ Doc agent")

# Brief project description, collapsed by default
with st.sidebar.expander("About", expanded=False):
    st.markdown(
        """
        **Engineering design assistant**

        Answers from loaded regulatory documents (PUE).
        Every answer is backed by a citation to clause, page, and section.
        """
    )

# Show which Qdrant collection is being queried
st.sidebar.caption(f"Collection: `{settings.QDRANT_COLLECTION_NAME}`")
st.sidebar.markdown("---")

# Advanced reasoning toggle – activates the agentic loop
use_advanced = st.sidebar.checkbox(
    "🧠 Advanced reasoning (decompose + verify)",
    value=False,
    help="For complex questions, splits the query into sub‑questions, "
         "iteratively retrieves relevant sections, and removes unsupported claims. "
         "Slower but more accurate for multi‑hop regulatory questions."
)
# Explain the toggle briefly
if use_advanced:
    st.sidebar.caption("Agentic mode active – may take a few seconds longer.")

# Button to start a fresh question (clears selected conversation)
if st.sidebar.button("➕ New Question", use_container_width=True):
    st.session_state.selected_index = None
    st.rerun()

st.sidebar.markdown("### 📚 Chat History")

if not st.session_state.history:
    st.sidebar.info("No conversations yet.")

# Render each previous question as a clickable button in the sidebar.
# The selected conversation is highlighted with the primary button style.
for idx, entry in enumerate(st.session_state.history):
    label = entry["question"][:50] + ("…" if len(entry["question"]) > 50 else "")
    
    is_selected = (idx == st.session_state.selected_index)
    button_style = "primary" if is_selected else "secondary"
    
    if st.sidebar.button(
        label=label,
        key=f"hist_{idx}",            # unique key per button
        use_container_width=True,
        type=button_style,
    ):
        st.session_state.selected_index = idx
        st.rerun()

st.sidebar.markdown("---")

# ---------------------------------------------------------------------------
# 6. Main area – Input handling
# ---------------------------------------------------------------------------
# The chat input is always visible at the bottom of the screen.
question = st.chat_input("Ask a question about the PUE…")

if question:
    # Select the active agent based on the checkbox
    with st.spinner("Searching the regulatory base…"):
        if use_advanced:
            # Use the agentic loop: decompose → judge → retrieve iteratively → verify
            result = agentic_agent.generate(question, system_prompt)
        else:
            # Use the fast, single‑pass retrieval and generation
            result = agent.generate(question, system_prompt)

    # Append the new Q&A pair to the history and select it immediately.
    new_entry = {
        "question": question,
        "answer": result.answer,
        "sources": result.sources,
    }
    st.session_state.history.append(new_entry)
    st.session_state.selected_index = len(st.session_state.history) - 1
    st.rerun()

# ---------------------------------------------------------------------------
# 7. Display Main Content
# ---------------------------------------------------------------------------
st.title("Doc agent: Regulatory Document Assistant")

# If a conversation is selected, show it; otherwise show the welcome screen.
if st.session_state.selected_index is not None and 0 <= st.session_state.selected_index < len(st.session_state.history):
    entry = st.session_state.history[st.session_state.selected_index]

    # User message bubble
    with st.chat_message("user", avatar="\U0001F464"):
        st.markdown(entry["question"])

    # Assistant message bubble
    with st.chat_message("assistant", avatar="⚡"):
        if entry["answer"]:
            raw_answer = entry["answer"]
            
            # Convert inline citations like [1], [2] into clickable links
            # that jump to the corresponding source anchor in the expander below.
            interactive_answer = re.sub(
                r"\[(\d+)\]",
                r"[\1](#source-\1)",
                raw_answer,
            )
            
            # Render the answer as Markdown; citations become active links.
            st.markdown(interactive_answer)

            # Expandable list of cited sources.
            # Each source has a hidden anchor div that the citation link targets.
            if entry["sources"]:
                with st.expander("📚 View Cited Sources", expanded=True):
                    for s in entry["sources"]:
                        # Invisible anchor target for the link
                        st.markdown(
                            f'<div id="source-{s.index}"></div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f"**[{s.index}]** `{s.doc_id}`  \n"
                            f"Pages {s.pages} — *{s.section}*"
                        )
            else:
                st.info("No sources were cited in the answer.")
        else:
            st.info("No answer generated.")
else:
    # Empty state – shown when no conversation is selected.
    st.markdown("<br><br>", unsafe_allow_html=True)
    cols = st.columns([1, 2, 1])
    with cols[1]:
        st.info("👋 **Welcome to Doc Agent!** \n\n Select a previous conversation from the sidebar or type a new question below to query the PUE database.", icon="💡")
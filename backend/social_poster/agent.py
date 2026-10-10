"""The social_poster agent. Build it here, following the labs in order
(docs/lab-1-build.html to start).

`root_agent` is the name ADK's tooling (`adk web`, the AG-UI bridge in
backend/main.py) looks for — define it as an `Agent` from `google.adk.agents`
once you get there.
"""

import os
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent / ".env")

from typing import Any, Optional

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.skills import load_skill_from_dir
from google.adk.tools import google_search, load_memory
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from google.adk.tools.skill_toolset import SkillToolset
from google.adk.tools.tool_context import ToolContext
from google.adk.memory.base_memory_service import MemoryEntry
from google.genai import types
from mcp import StdioServerParameters

from . import db
from .tools import generate_image

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILLS_DIR = PROJECT_ROOT / "skills"
MCP_SERVER = PROJECT_ROOT / "mcp" / "linkedin_server.py"

BUFFER_API_KEY = os.environ.get("BUFFER_API_KEY", "")

buffer_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://mcp.buffer.com/mcp",
        headers={"Authorization": f"Bearer {BUFFER_API_KEY}"},
    ),
    require_confirmation=True,
)

linkedin_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[str(MCP_SERVER)],
            env={
                "DRY_RUN": os.environ.get("DRY_RUN", "true"),
                "LINKEDIN_ACCESS_TOKEN": os.environ.get("LINKEDIN_ACCESS_TOKEN", ""),
            },
        ),
    ),
    tool_filter=["get_profile", "create_post"],
    # Buffer's server also has a create_post; Gemini rejects two functions with
    # the same name. The prefix renames these to linkedin_get_profile and
    # linkedin_create_post. The filter above still uses the original names.
    tool_name_prefix="linkedin",
    require_confirmation=True,
)

# POST_VIA overrides the LLM's own routing: "buffer" drops the LinkedIn
# tool entirely, "linkedin" drops Buffer even if a key is set. Blank
# exposes both and lets the agent route by what the user asks for.
POST_VIA = os.environ.get("POST_VIA", "").strip().lower()
use_linkedin = POST_VIA != "buffer"
use_buffer = bool(BUFFER_API_KEY) and POST_VIA != "linkedin"

# Memory is available on Agent Runtime (injected APP_URL) or when explicitly enabled
ENABLE_MEMORY = (
    os.environ.get("ENABLE_MEMORY", "").strip().lower()
    or os.environ.get("USE_MEMORY", "").strip().lower()
    or os.environ.get("MEMORY_AVAILABLE", "").strip().lower()
)
use_memory = (
    ENABLE_MEMORY in ("true", "1", "yes")
    or (bool(os.environ.get("APP_URL")) and ENABLE_MEMORY != "false")
)

skill_toolset = SkillToolset(
    skills=[
        load_skill_from_dir(SKILLS_DIR / "post-formatter"),
        load_skill_from_dir(SKILLS_DIR / "platform-style"),
        load_skill_from_dir(SKILLS_DIR / "brand-voice"),
        load_skill_from_dir(SKILLS_DIR / "poster-style"),
    ],
)

RESEARCH_MODEL = os.environ.get("RESEARCH_MODEL", "gemini-2.5-flash")
ORCHESTRATOR_MODEL = os.environ.get("ORCHESTRATOR_MODEL", "gemini-2.5-flash")

search_agent = Agent(
    name="web_researcher",
    model=RESEARCH_MODEL,
    description="Researches facts, dates, and context on the web.",
    instruction="Research the given query and return a concise summary of relevant facts.",
    tools=[google_search],
)

async def save_memory(fact: str, tool_context: ToolContext) -> str:
    """Saves an important user fact, preference, profile detail, or instruction to permanent memory."""
    if not tool_context._invocation_context.memory_service:
        return "Memory service not available."
    entry = MemoryEntry(content=types.Content(parts=[types.Part.from_text(text=fact)]))
    await tool_context._invocation_context.memory_service.add_memory(
        app_name=tool_context._invocation_context.session.app_name,
        user_id=tool_context._invocation_context.session.user_id,
        memories=[entry],
    )
    return f"Saved to permanent memory: {fact}"


tools = [AgentTool(agent=search_agent), generate_image, skill_toolset]
if use_memory:
    tools.append(load_memory)
    tools.append(save_memory)
if use_buffer:
    tools.append(buffer_toolset)
if use_linkedin:
    tools.append(linkedin_toolset)

# Stage tracking: idea -> consulting_memory -> researching -> drafting -> awaiting_approval -> posted
_TOOL_STAGES = {
    "load_memory": "consulting_memory",
    "web_researcher": "researching",
    "load_skill": "drafting",
    "generate_image": "drafting",
}


def _init_stage(callback_context: CallbackContext) -> None:
    if "pipeline_stage" not in callback_context.state:
        callback_context.state["pipeline_stage"] = "idea"


def _track_stage(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict
) -> Optional[dict]:
    if tool.name in _TOOL_STAGES:
        tool_context.state["pipeline_stage"] = _TOOL_STAGES[tool.name]
    elif tool.name in ("create_post", "linkedin_create_post") and tool_response.get("isError") is not True:
        tool_context.state["pipeline_stage"] = "posted"  # only a completed MCP call
        platform = "Buffer" if "channelId" in args else "LinkedIn"
        post_url = tool_response.get("post_url") or tool_response.get("url")
        db.save_post(
            platform=platform,
            text=args.get("text", ""),
            post_url=post_url,
            image_path=args.get("image_path"),
        )
    return None  # never modify the tool result


def _stage_after_agent(callback_context: CallbackContext) -> None:
    # A turn that ends mid-pipeline is waiting on the user (draft approval).
    if callback_context.state.get("pipeline_stage") in (
        "consulting_memory",
        "researching",
        "drafting",
    ):
        callback_context.state["pipeline_stage"] = "awaiting_approval"


root_agent = Agent(
    name="social_poster",
    model=ORCHESTRATOR_MODEL,
    description="Helps the user turn an idea into a polished social media post.",
    instruction="""You help the user turn an idea into a social media post.

Workflow:
1. If memory is available:
   - Call load_memory with a query to recall past posts, preferences, voice, or user details before drafting.
   - If the user shares a fact about themselves, a style preference, or asks you to remember something (e.g. "my name is Ian", "remember this"), call save_memory to save it permanently.
2. If the idea needs facts, dates, or context, research it with the
   web_researcher tool first.
3. When drafting, load and follow the relevant skills: post-formatter
   (structure), platform-style (rules for the target platform), and
   brand-voice (tone).
4. If the user asks for an image, load and follow the poster-style skill,
   then call generate_image with a detailed visual description and tell
   them where the file was saved.
5. ALWAYS show the finished draft to the user and ask for their approval
   before any posting action.
   - Choose LinkedIn for an immediate post with an image.
   - Choose Buffer for scheduling or other platforms (and for an immediate Buffer post, ask Buffer to publish now rather than schedule).

Posting rules (strict):
- Only post AFTER the user has explicitly approved the exact draft shown to
  them. "Yes", "post it" counts; enthusiasm about the idea does not.
- After posting, share the returned confirmation with the user.""",
    tools=tools,
    before_agent_callback=_init_stage,
    after_tool_callback=_track_stage,
    after_agent_callback=_stage_after_agent,
)


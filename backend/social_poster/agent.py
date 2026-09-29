"""The social_poster agent. Build it here, following the labs in order
(docs/lab-1-build.html to start).

`root_agent` is the name ADK's tooling (`adk web`, the AG-UI bridge in
backend/main.py) looks for — define it as an `Agent` from `google.adk.agents`
once you get there.
"""

from google.adk.agents import Agent
from .tools import generate_image

root_agent = Agent(
    name="social_poster",
    model="gemini-flash-latest",
    description="Helps the user turn an idea into a polished social media post.",
    instruction="""You help the user turn an idea into a social media post.
If the user asks for an image, call generate_image with a detailed visual
description and tell them where the file was saved.""",
    tools=[generate_image],
)


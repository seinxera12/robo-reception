# app/agent/core.py
import logging
import time

from pydantic_ai import Agent
from pydantic_ai.models.groq import GroqModel

from app.config import settings
from app.agent.models import RoboDeps

logger = logging.getLogger(__name__)


# ── Model setup ────────────────────────────────────────────────────────────

def _get_model() -> GroqModel:
    """Return configured Groq model, passing api_key explicitly from settings."""
    from pydantic_ai.providers.groq import GroqProvider
    return GroqModel(
        "meta-llama/llama-4-scout-17b-16e-instruct",
        provider=GroqProvider(api_key=settings.groq_api_key or "placeholder-set-GROQ_API_KEY"),
    )


# ── Agent definition ───────────────────────────────────────────────────────

agent = Agent(
    model=_get_model(),
    deps_type=RoboDeps,
    retries=2,  # retry on tool validation failure
)


@agent.system_prompt
def _system_prompt(ctx) -> str:
    """Called fresh on every agent run — injects current timestamp."""
    from app.agent.prompts import build_system_prompt
    return build_system_prompt(ctx)


# ── Main entry point ───────────────────────────────────────────────────────

async def run_agent(
    utterance: str,
    deps: RoboDeps,
    conversation_history: list,
) -> str:
    """
    Run the agent on a single user utterance.
    Returns the response text to be passed to TTS.
    """
    t0 = time.time()
    logger.info(f"Agent run: '{utterance[:80]}'")

    try:
        result = await agent.run(
            utterance,
            deps=deps,
            message_history=conversation_history,
        )
        elapsed = time.time() - t0
        response = result.output
        logger.info(f"Agent response ({elapsed:.2f}s): '{response[:80]}'")
        return response

    except Exception as e:
        logger.exception(f"Agent error: {e}")
        return "I'm sorry, I ran into a problem. Could you please repeat that?"


# ── Tool registration ──────────────────────────────────────────────────────
# Tool modules are imported here, AFTER the agent is defined.
# The @agent.tool decorators in each module register against this agent object.
# Do NOT move these imports above the agent definition.

def _register_tools() -> None:
    import app.tools.appointments  # registers: lookup_appointment, check_availability
    import app.tools.info          # registers: get_info
    # Day 4: import app.tools.notifications  — notify_host, update_checkin_status
    # Day 4: import app.tools.wayfinding     — get_directions
    # Day 4: import app.tools.hosts          — list_hosts


_register_tools()

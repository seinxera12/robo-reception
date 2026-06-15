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


# ── Tool call trace ────────────────────────────────────────────────────────

def _log_tool_trace(result: object) -> None:
    """
    Walk the completed run's message history and emit one INFO line per tool
    call and one per tool return. Payload is truncated to 120 chars so the
    terminal stays readable.

    Format:
      ▶ tool call  : tool_name({"arg": "value"…})
      ◀ tool return: tool_name → {"found": true, …}
    """
    try:
        from pydantic_ai.messages import (
            ModelResponse,
            ModelRequest,
            ToolCallPart,
            ToolReturnPart,
        )

        pending: dict[str, str] = {}  # tool_call_id → tool_name

        for msg in result.all_messages():  # type: ignore[union-attr]
            if isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        # args_as_json_str() is the cleanest serialisation
                        try:
                            raw = part.args_as_json_str()
                        except Exception:
                            raw = str(part.args)
                        snippet = raw[:120] + ("…" if len(raw) > 120 else "")
                        pending[part.tool_call_id] = part.tool_name
                        logger.info(f"  ▶ {part.tool_name}({snippet})")

            elif isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        name = pending.pop(part.tool_call_id, "?")
                        ret = str(part.content)
                        snippet = ret[:120] + ("…" if len(ret) > 120 else "")
                        logger.info(f"  ◀ {name} → {snippet}")

    except Exception as exc:
        logger.debug(f"  tool trace unavailable: {exc}")


# ── Main entry point ───────────────────────────────────────────────────────

async def run_agent(
    utterance: str,
    deps: RoboDeps,
    conversation_history: list,
) -> tuple[str, object]:
    """
    Run the agent on a single user utterance.
    Returns (response_text, result) — caller uses result.all_messages_json()
    to persist conversation history.
    """
    t0 = time.time()
    logger.info(f"  ┌ user  : '{utterance[:120]}'")

    try:
        result = await agent.run(
            utterance,
            deps=deps,
            message_history=conversation_history,
        )
        elapsed = time.time() - t0
        response = result.output

        # Emit per-tool ▶/◀ lines from the completed message history
        _log_tool_trace(result)

        logger.info(f"  └ robo  : '{response[:120]}' ({elapsed:.2f}s)")
        return response, result

    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"  └ agent error ({elapsed:.2f}s): {e}")
        logger.debug("  agent exception:", exc_info=True)
        return "I'm sorry, I ran into a problem. Could you please repeat that?", None


# ── Tool registration ──────────────────────────────────────────────────────
# Tool modules are imported AFTER the agent is defined.
# The @agent.tool decorators register against this agent object.
# Do NOT move these imports above the agent definition.

def _register_tools() -> None:
    import app.tools.appointments   # lookup_appointment, check_availability, update_checkin_status
    import app.tools.info           # get_info
    import app.tools.notifications  # notify_host
    import app.tools.hosts          # list_hosts


_register_tools()

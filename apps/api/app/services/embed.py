from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import rental as rental_service
from app.services.onboarding import (
    build_welcome_message,
    get_onboarding_answers,
    get_onboarding_questions,
    is_onboarding_complete,
)


async def bootstrap(session, web_base_url: str) -> dict:
    agent = session.rental.agent
    agent_version = session.rental.agent_version
    context = session.context_metadata or {}
    complete = is_onboarding_complete(context)
    answers = get_onboarding_answers(context)

    return {
        "agent_name": agent.name,
        "agent_slug": agent.slug,
        "session_id": str(session.id),
        "expires_at": session.expires_at.isoformat(),
        "onboarding_complete": complete,
        "questions": [] if complete else get_onboarding_questions(agent_version),
        "welcome_message": build_welcome_message(agent.name, answers) if complete else None,
        "widget_url": f"{web_base_url.rstrip('/')}/embed/chat",
    }


async def submit_onboarding(db: AsyncSession, session, answers: dict[str, str]) -> dict:
    agent = session.rental.agent
    agent_version = session.rental.agent_version
    questions = get_onboarding_questions(agent_version)
    required_ids = {q["id"] for q in questions}

    cleaned = {k: v.strip() for k, v in answers.items() if v and v.strip()}
    missing = required_ids - set(cleaned.keys())
    if missing:
        from app.core.errors import bad_request

        raise bad_request(
            code="ONBOARDING_INCOMPLETE",
            message=f"Missing answers for: {', '.join(sorted(missing))}",
        )

    session.context_metadata = {
        "onboarding_complete": True,
        "onboarding_answers": cleaned,
        "onboarding_completed_at": datetime.now(UTC).isoformat(),
    }
    welcome = build_welcome_message(agent.name, cleaned)
    return {"onboarding_complete": True, "welcome_message": welcome}


async def chat(
    db: AsyncSession,
    session,
    message: str,
    request_id: str | None,
) -> dict:
    if not is_onboarding_complete(session.context_metadata):
        from app.core.errors import bad_request

        raise bad_request(
            code="ONBOARDING_REQUIRED",
            message="Complete onboarding before chatting with the agent.",
        )

    await rental_service.validate_session_active(session)
    answers = get_onboarding_answers(session.context_metadata)
    context = {
        "source": "embed_widget",
        "onboarding": answers,
    }

    execution = await rental_service.execute_agent(
        db,
        session,
        input_data=message,
        context=context,
        request_id=request_id,
    )
    output = execution.output_metadata or {}
    reply = ""
    approval_id = None

    if output.get("status") == "waiting_for_approval":
        approval = output.get("approval", {})
        reply = f"⏸ **{approval.get('title', 'Approval required')}**\n{approval.get('description', '')}"
        from sqlalchemy import select
        from app.models import ApprovalRequest, ApprovalStatus

        result = await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.execution_id == execution.id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        )
        pending = result.scalar_one_or_none()
        if pending:
            approval_id = str(pending.id)
    elif output.get("status") == "completed":
        out = output.get("output")
        reply = out if isinstance(out, str) else str(out)
    else:
        reply = output.get("message", "I processed your request.")

    return {
        "execution_id": str(execution.id),
        "status": execution.status.value,
        "reply": reply,
        "output": output.get("output"),
        "approval_id": approval_id,
    }


def build_embed_snippet(api_key: str, web_base_url: str) -> dict:
    base = web_base_url.rstrip("/")
    script = (
        f'<script src="{base}/embed.js" '
        f'data-api-key="{api_key}" '
        f'data-agenthub-url="{base}" async></script>'
    )
    html = f"<!-- AgentHub Agent Widget -->\n{script}"
    return {
        "api_key": api_key,
        "embed_html": html,
        "embed_script": script,
        "demo_page_url": f"{base}/embed/demo?key={api_key}",
    }

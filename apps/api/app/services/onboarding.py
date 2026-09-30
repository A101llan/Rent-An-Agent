"""Onboarding questions — read from the agent version manifest.

Each agent's manifest may contain an "onboarding" block:

    {
      "onboarding": {
        "questions": [
          {
            "id": "company_name",
            "question": "What company are you supporting?",
            "placeholder": "e.g. Acme Corp"
          }
        ]
      }
    }

If the manifest has no "onboarding" key, a universal default set is used so
that every agent gets *some* context without any developer action required.
"""

DEFAULT_QUESTIONS: list[dict[str, str]] = [
    {
        "id": "company_name",
        "question": "What company or team is this agent working with?",
        "placeholder": "e.g. Operations team at Acme Corp",
    },
    {
        "id": "workflow",
        "question": "Describe the main task you want help with.",
        "placeholder": "e.g. reviewing supplier emails before approval",
    },
]


def get_onboarding_questions(agent_version=None) -> list[dict[str, str]]:
    """Return the onboarding questions for an agent.

    Priority:
      1. agent_version.manifest["onboarding"]["questions"]  (developer-defined)
      2. DEFAULT_QUESTIONS                                   (universal fallback)
    """
    if agent_version is not None:
        manifest = agent_version.manifest or {}
        questions = manifest.get("onboarding", {}).get("questions", [])
        if questions:
            return questions
    return DEFAULT_QUESTIONS


def is_onboarding_complete(context: dict | None) -> bool:
    if not context:
        return False
    return bool(context.get("onboarding_complete"))


def get_onboarding_answers(context: dict | None) -> dict[str, str]:
    if not context:
        return {}
    return dict(context.get("onboarding_answers") or {})


def build_welcome_message(agent_name: str, answers: dict[str, str]) -> str:
    lines = [f"Hi! I'm **{agent_name}** and I'm ready to work in your environment."]
    if answers:
        lines.append("")
        lines.append("Here's what I understand about your setup:")
        for key, value in answers.items():
            label = key.replace("_", " ").title()
            lines.append(f"- **{label}:** {value}")
    lines.append("")
    lines.append("Ask me anything — I'll use this context to give relevant answers.")
    return "\n".join(lines)

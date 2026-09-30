"""High-risk action detection in mock handlers."""

HIGH_RISK_ACTIONS = {
    "send email": ("SEND_EMAIL", "Send Email", "Agent wants to send an email on your behalf."),
    "delete record": ("DELETE_RECORD", "Delete Record", "Agent wants to delete a record."),
    "execute payment": ("EXECUTE_PAYMENT", "Execute Payment", "Agent wants to process a payment."),
    "purchase order": ("CREATE_PURCHASE_ORDER", "Create Purchase Order", "Agent wants to create a purchase order."),
}


def check_high_risk(text: str) -> dict | None:
    lower = text.lower()
    for keyword, (action, title, desc) in HIGH_RISK_ACTIONS.items():
        if keyword in lower:
            return {
                "status": "waiting_for_approval",
                "action": action,
                "approval": {
                    "title": title,
                    "description": desc,
                    "details": {"keyword": keyword, "input_preview": text[:200]},
                },
                "usage": {"input_tokens": 20, "output_tokens": 0},
            }
    return None

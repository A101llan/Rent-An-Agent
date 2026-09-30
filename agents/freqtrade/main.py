import asyncio
import logging
from agenthub import AgentClient, ApprovalRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_freqtrade_agent():
    client = AgentClient("freqtrade")
    
    @client.on_request
    async def handle_trade(request, context):
        logger.info(f"Received trade request: {request}")
        
        # Check permissions
        if not context.has_permission("trade_execution"):
            return {"error": "Missing trade_execution permission"}
            
        # Example of Human Approval before a large trade
        if request.get("amount", 0) > 1000:
            approval = await client.request_approval(
                ApprovalRequest(
                    reason=f"High value trade requested: {request.get('amount')}",
                    severity="high"
                )
            )
            if not approval.approved:
                return {"error": "Trade denied by user"}

        # (Here we would invoke the actual freqtrade strategy execution)
        return {"status": "success", "message": "Trade executed via Freqtrade"}

    await client.start()

if __name__ == "__main__":
    asyncio.run(run_freqtrade_agent())

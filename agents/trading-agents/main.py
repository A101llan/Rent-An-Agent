import asyncio
import logging
from agenthub import AgentClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_trading_agents():
    client = AgentClient("trading-agents")
    
    @client.on_request
    async def handle_analysis(request, context):
        logger.info(f"Received LLM analysis request: {request}")
        # Pass to TradingAgents LLM framework
        return {"status": "success", "analysis": "Bullish sentiment detected"}

    await client.start()

if __name__ == "__main__":
    asyncio.run(run_trading_agents())

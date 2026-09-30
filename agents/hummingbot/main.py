import asyncio
import logging
from agenthub import AgentClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_hummingbot_agent():
    client = AgentClient("hummingbot")
    
    @client.on_request
    async def handle_strategy(request, context):
        logger.info(f"Received market making strategy config: {request}")
        # Apply hummingbot config dynamically here
        return {"status": "success", "message": "Strategy updated"}

    await client.start()

if __name__ == "__main__":
    asyncio.run(run_hummingbot_agent())

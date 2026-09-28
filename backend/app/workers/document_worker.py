import time
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("connector_ai.worker")


async def run_worker_loop():
    logger.info("AI Background Worker started successfully.")
    while True:
        try:
            # Polling for background document extraction or re-indexing
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            logger.info("AI Worker stopped.")
            break
        except Exception as e:
            logger.error(f"Worker iteration error: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run_worker_loop())


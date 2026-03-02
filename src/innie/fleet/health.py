"""Fleet health monitor — background polling of server agents."""

import asyncio
import logging
import time
from datetime import datetime

import httpx

from innie.fleet.models import Agent, AgentStatus, AgentType, FleetStats

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Periodically checks /health on all SERVER agents."""

    def __init__(
        self,
        agents: dict[str, Agent],
        interval: int = 30,
        timeout: int = 10,
        failure_threshold: int = 3,
    ):
        self.agents = agents
        self.interval = interval
        self.timeout = timeout
        self.failure_threshold = failure_threshold
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        # Run initial check immediately
        await self._check_all()
        while True:
            await asyncio.sleep(self.interval)
            await self._check_all()

    async def _check_all(self):
        tasks = []
        for agent_id, agent in self.agents.items():
            if agent.agent_type == AgentType.SERVER:
                tasks.append(self._check_agent(agent_id))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_agent(self, agent_id: str):
        agent = self.agents.get(agent_id)
        if not agent:
            return

        health = agent.health
        health.last_check = datetime.utcnow().isoformat()

        try:
            start = time.monotonic()
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{agent.endpoint}/health",
                    timeout=self.timeout,
                )
            elapsed_ms = (time.monotonic() - start) * 1000

            if resp.status_code == 200:
                health.status = AgentStatus.ONLINE
                health.consecutive_failures = 0
                health.last_success = health.last_check
                health.response_time_ms = elapsed_ms
                health.error = None
                try:
                    data = resp.json()
                    health.version = data.get("version")
                except Exception:
                    pass
            else:
                self._record_failure(health, f"HTTP {resp.status_code}")

        except httpx.TimeoutException:
            self._record_failure(health, "Timeout")
        except httpx.ConnectError:
            self._record_failure(health, "Connection failed")
        except Exception as e:
            self._record_failure(health, str(e))

    def _record_failure(self, health, error: str):
        health.consecutive_failures += 1
        health.error = error
        if health.consecutive_failures >= self.failure_threshold:
            health.status = AgentStatus.OFFLINE
        else:
            health.status = AgentStatus.DEGRADED

    async def check_now(self, agent_id: str):
        """Force immediate health check on a specific agent."""
        await self._check_agent(agent_id)

    def get_stats(self) -> FleetStats:
        stats = FleetStats()
        response_times = []

        for agent in self.agents.values():
            if agent.agent_type != AgentType.SERVER:
                continue

            stats.total_agents += 1
            status = agent.health.status

            if status == AgentStatus.ONLINE:
                stats.online_count += 1
                if agent.health.response_time_ms is not None:
                    response_times.append(agent.health.response_time_ms)
            elif status == AgentStatus.OFFLINE:
                stats.offline_count += 1
            elif status == AgentStatus.DEGRADED:
                stats.degraded_count += 1
            else:
                stats.unknown_count += 1

            if agent.expected_online:
                stats.expected_online_count += 1
                if status in (AgentStatus.OFFLINE, AgentStatus.UNKNOWN):
                    stats.unexpected_offline_count += 1

        if response_times:
            stats.avg_response_time_ms = sum(response_times) / len(response_times)

        stats.last_updated = datetime.utcnow().isoformat()
        return stats

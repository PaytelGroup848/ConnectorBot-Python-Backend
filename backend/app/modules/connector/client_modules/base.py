import asyncio
import logging
import datetime
from typing import Optional, Dict, Any, List, Tuple
import httpx
from app.core.config import settings

logger = logging.getLogger("connector_ai.connector_client")

# Common Tally Prime XML/ODBC Server ports configured across businesses
CANDIDATE_TALLY_PORTS = [9000, 9001, 9002, 9003, 9090, 9999]


class BaseConnectorClient:
    """Base HTTP client handling connection pooling, heartbeats, and live port auto-detection."""
    def __init__(self):
        self.base_url = settings.CONNECTOR_API_BASE_URL
        self.timeout = settings.CONNECTOR_TIMEOUT_SECONDS
        self._client: Optional[httpx.AsyncClient] = None
        # Per-user / per-company dynamic port & heartbeat registry
        self._user_port_registry: Dict[str, Dict[str, Any]] = {}

    def register_heartbeat(
        self,
        tally_port: int,
        company_name: Optional[str] = None,
        user_email: Optional[str] = None,
        is_online: bool = True,
        agent_version: str = "1.0.1",
    ) -> Dict[str, Any]:
        """Registers or updates a user/company's active Tally Prime port from Desktop Agent or CtrlBooks session."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record = {
            "tally_port": int(tally_port),
            "company_name": company_name or "Default",
            "user_email": user_email or "anonymous",
            "is_online": is_online,
            "agent_version": agent_version,
            "last_heartbeat": now_iso,
            "detection_source": "DESKTOP_AGENT_HEARTBEAT",
        }
        if user_email:
            self._user_port_registry[f"user:{user_email.lower().strip()}"] = record
        if company_name:
            self._user_port_registry[f"company:{company_name.lower().strip()}"] = record
        self._user_port_registry["latest"] = record
        return record

    async def _probe_single_port(self, host: str, port: int, timeout: float = 0.12) -> Optional[int]:
        """Probes a single local TCP port to check if Tally Prime XML Server is listening."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return port
        except Exception:
            return None

    async def _auto_detect_local_tally_port(self, preferred_port: Optional[int] = None) -> Tuple[Optional[int], List[int]]:
        """Scans candidate Tally Prime ports in parallel on localhost (127.0.0.1) to detect active Tally port."""
        ports_to_scan: List[int] = []
        if preferred_port and int(preferred_port) > 0:
            ports_to_scan.append(int(preferred_port))
        for p in CANDIDATE_TALLY_PORTS:
            if p not in ports_to_scan:
                ports_to_scan.append(p)

        results = await asyncio.gather(
            *(self._probe_single_port("127.0.0.1", p) for p in ports_to_scan),
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, int) and res > 0:
                return res, ports_to_scan
        return None, ports_to_scan

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=3.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        token: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Connector-AI-Assistant/1.0",
        }
        active_token = token or settings.CONNECTOR_API_TOKEN
        if active_token:
            headers["Authorization"] = f"Bearer {active_token}"

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            client = await self._get_client()
            res = await client.request(method=method, url=url, headers=headers, params=params, json=json_data)
            if res.status_code in [200, 201]:
                return res.json()
            if (
                res.status_code in [401, 403]
                and token
                and token != settings.CONNECTOR_API_TOKEN
                and settings.CONNECTOR_API_TOKEN
            ):
                logger.warning(
                    f"Connector API token returned {res.status_code} for {url}, retrying with server CONNECTOR_API_TOKEN"
                )
                headers["Authorization"] = f"Bearer {settings.CONNECTOR_API_TOKEN}"
                res = await client.request(method=method, url=url, headers=headers, params=params, json=json_data)
                if res.status_code in [200, 201]:
                    return res.json()
            if res.status_code == 401:
                logger.debug(f"Connector API returned status {res.status_code} for {url}")
            else:
                logger.warning(f"Connector API returned status {res.status_code} for {url}")
            return {"success": False, "statusCode": res.status_code, "data": None}
        except Exception as e:
            logger.error(f"Error calling Connector API {url}: {e}")
            return {"success": False, "error": str(e), "data": None}


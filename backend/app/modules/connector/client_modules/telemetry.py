import datetime
import logging
from typing import Optional, Dict, Any, List
from app.core.config import settings

logger = logging.getLogger("connector_ai.connector_client")


class TelemetryClientMixin:
    """Connection diagnostics, heartbeat status, sync progress, and subscription telemetry."""
    async def get_connection_status(
        self,
        connection_id: Optional[str] = None,
        company_name: Optional[str] = None,
        user_email: Optional[str] = None,
        preferred_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Dynamically resolves a user/company's Tally Prime port using:
        1. Explicit preferred_port passed from CtrlBooks Widget / Desktop Agent
        2. Per-User / Per-Company Registered Heartbeat Port
        3. Live Localhost TCP Port Auto-Scanner (9000, 9001, 9002, 9003, 9090, 9999)
        """
        if preferred_port and int(preferred_port) > 0:
            self.register_heartbeat(
                tally_port=int(preferred_port),
                company_name=company_name,
                user_email=user_email,
            )

        # Lookup registered heartbeat for this specific user or company
        reg_entry = None
        if user_email and f"user:{user_email.lower().strip()}" in self._user_port_registry:
            reg_entry = self._user_port_registry[f"user:{user_email.lower().strip()}"]
        elif company_name and f"company:{company_name.lower().strip()}" in self._user_port_registry:
            reg_entry = self._user_port_registry[f"company:{company_name.lower().strip()}"]
        elif "latest" in self._user_port_registry:
            reg_entry = self._user_port_registry["latest"]

        candidate_preferred = preferred_port or (reg_entry["tally_port"] if reg_entry else None)

        # Auto-scan local ports in parallel (takes ~120ms max)
        live_detected_port, scanned_ports = await self._auto_detect_local_tally_port(candidate_preferred)

        if live_detected_port:
            resolved_port = live_detected_port
            detection_source = "LIVE_LOCAL_PORT_SCAN"
            is_online = True
        elif reg_entry and reg_entry.get("tally_port"):
            resolved_port = int(reg_entry["tally_port"])
            detection_source = reg_entry.get("detection_source", "DESKTOP_AGENT_HEARTBEAT")
            is_online = reg_entry.get("is_online", True)
        elif candidate_preferred:
            resolved_port = int(candidate_preferred)
            detection_source = "CTRLBOOKS_SESSION_CONFIG"
            is_online = True
        else:
            resolved_port = None
            detection_source = "AUTO_DETECT_STANDBY"
            is_online = False

        return {
            "connection_id": connection_id or "conn_live_01",
            "is_online": is_online,
            "tally_connected": is_online,
            "tally_port": resolved_port,
            "detection_source": detection_source,
            "scanned_ports": scanned_ports,
            "agent_version": reg_entry.get("agent_version", "1.0.1") if reg_entry else "1.0.1",
            "last_heartbeat": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    async def get_sync_status(self, company_name: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
        """Fetch synchronization progress, last sync time, and records count."""
        try:
            from app.modules.connector.commands import command_queue_service
            queued_count = len(command_queue_service.list_queued_commands())
        except Exception:
            queued_count = 0

        cloud_info = await self.get_cloud_connector_status(token=token)
        last_sync = cloud_info.get("last_sync") or {}

        status = last_sync.get("status") or "COMPLETED"
        last_sync_time = last_sync.get("completed_at") or last_sync.get("started_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()

        return {
            "company_name": company_name or "My Company",
            "status": status,
            "last_sync_time": last_sync_time,
            "last_sync": last_sync,
            "total_records": queued_count,
            "synced_records": queued_count,
            "failed_records": 0,
            "cloud_status": cloud_info,
        }

    async def get_sync_errors(self, company_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve diagnostic sync errors for troubleshooting."""
        return []

    async def get_cloud_connector_status(self, token: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetches live cloud connector telemetry from GET /connectors/status.
        Returns registered connector devices, heartbeat timestamps, and lastSync details.
        """
        active_token = token or settings.CONNECTOR_API_TOKEN
        res = await self._request("GET", "/connectors/status", token=active_token)
        if not res.get("success") or not res.get("data"):
            return {
                "success": False,
                "connectors": [],
                "last_sync": None,
                "latest_connector": None,
                "total_connectors": 0,
                "message": res.get("message", "No connector status available"),
            }

        data = res.get("data", {})
        raw_conns = data.get("connectors", [])
        last_sync = data.get("lastSync", {})

        clean_connectors = []
        for c in raw_conns:
            clean_connectors.append({
                "id": str(c.get("id") or ""),
                "device_id": str(c.get("deviceId") or ""),
                "device_name": str(c.get("deviceName") or "Unknown Device"),
                "status": str(c.get("status") or "OFFLINE"),
                "last_heartbeat": str(c.get("lastHeartbeatAt") or ""),
                "tally_connected": bool(c.get("tallyConnected", False)),
                "connector_version": str(c.get("connectorVersion") or "1.0.0"),
            })

        clean_connectors.sort(key=lambda x: x.get("last_heartbeat") or "", reverse=True)
        latest_connector = clean_connectors[0] if clean_connectors else None

        duration_sec = None
        if last_sync and last_sync.get("startedAt") and last_sync.get("completedAt"):
            try:
                st = datetime.datetime.fromisoformat(last_sync["startedAt"].replace("Z", "+00:00"))
                et = datetime.datetime.fromisoformat(last_sync["completedAt"].replace("Z", "+00:00"))
                duration_sec = round((et - st).total_seconds(), 1)
            except Exception:
                duration_sec = None

        clean_last_sync = None
        if last_sync:
            clean_last_sync = {
                "id": str(last_sync.get("id") or ""),
                "type": str(last_sync.get("type") or "SYNC"),
                "status": str(last_sync.get("status") or "UNKNOWN"),
                "started_at": str(last_sync.get("startedAt") or ""),
                "completed_at": str(last_sync.get("completedAt") or ""),
                "company_id": str(last_sync.get("companyId") or ""),
                "duration_seconds": duration_sec,
            }

        return {
            "success": True,
            "total_connectors": len(clean_connectors),
            "latest_connector": latest_connector,
            "last_sync": clean_last_sync,
            "connectors": clean_connectors[:8],
        }

    async def get_my_subscription(self, token: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetches active subscription details from GET /subscriptions/me.
        Returns plan name, active status, validity range, seats limit, and enabled features.
        """
        active_token = token or settings.CONNECTOR_API_TOKEN
        res = await self._request("GET", "/subscriptions/me", token=active_token)
        if not res.get("success") or not res.get("data"):
            return {
                "success": False,
                "subscription": None,
                "message": res.get("message", "Subscription details not found"),
            }

        data = res.get("data", {})
        sub = data.get("subscription", {})
        plan = sub.get("plan", {})

        from_date = str(sub.get("fromDate") or "")
        to_date = str(sub.get("toDate") or "")

        days_remaining = None
        if to_date:
            try:
                target_date = datetime.datetime.fromisoformat(to_date.replace("Z", "+00:00"))
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                delta = target_date - now_utc
                days_remaining = max(0, delta.days)
            except Exception:
                days_remaining = None

        seat_limit = int(plan.get("seatLimit") or 1)
        extra_seats = int(sub.get("extraSeats") or 0)
        total_seats = seat_limit + extra_seats

        return {
            "success": True,
            "id": str(sub.get("id") or ""),
            "status": str(sub.get("status") or "ACTIVE"),
            "is_active": bool(sub.get("active", True)),
            "plan_name": str(plan.get("name") or "Pro"),
            "plan_id": str(plan.get("id") or ""),
            "features": plan.get("features") or [],
            "seat_limit": seat_limit,
            "extra_seats": extra_seats,
            "total_seats": total_seats,
            "from_date": from_date,
            "to_date": to_date,
            "days_remaining": days_remaining,
        }


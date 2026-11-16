from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from broker_node.shared.db import connect


class AmbiguousOrderLinkError(RuntimeError):
    pass


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _matches(candidate: Any, normalized: dict[str, Any]) -> bool:
    payload = json.loads(candidate["payload_json"])
    instrument = normalized.get("instrument") or {}
    if payload.get("code") != instrument.get("code") or payload.get("exchange") != instrument.get("exchange"):
        return False
    if payload.get("side") != normalized.get("side"):
        return False
    if payload.get("price") is None or normalized.get("price") is None:
        return False
    if payload.get("quantity") is None:
        return False
    if Decimal(str(payload.get("price"))) != Decimal(str(normalized.get("price"))):
        return False
    observed_quantity = normalized.get("quantity")
    if observed_quantity is not None and int(observed_quantity) > int(payload.get("quantity")):
        return False
    observed_time = _time(normalized.get("created_at") or normalized.get("occurred_at"))
    command_time = _time(candidate["created_at"])
    if observed_time and command_time:
        age = (observed_time - command_time).total_seconds()
        if age < 0 or age > 300:
            return False
    return True


def resolve_local_order_id(durable_db, normalized: dict[str, Any]) -> dict[str, str] | None:
    """Resolve a GM callback to one durable local submit command.

    GM owns ``cl_ord_id`` and may replace it with its own UUID.  Resolution is
    based on an existing broker alias or one unambiguous matching submit
    command; zero or multiple candidates are explicit unresolved cases.
    """
    broker_client_order_id = normalized.get("client_order_id")
    broker_order_id = normalized.get("broker_order_id")
    with connect(durable_db) as connection:
        link = connection.execute(
            """
            SELECT client_order_id, submit_command_id
            FROM order_links
            WHERE broker_order_id = ? OR broker_client_order_id = ? OR client_order_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (broker_order_id, broker_client_order_id, broker_client_order_id),
        ).fetchone()
        if link:
            connection.execute(
                """
                UPDATE order_links
                SET broker_client_order_id = COALESCE(?, broker_client_order_id),
                    broker_order_id = COALESCE(?, broker_order_id),
                    updated_at = ?
                WHERE client_order_id = ?
                """,
                (broker_client_order_id, broker_order_id, datetime.now().astimezone().isoformat(), link["client_order_id"]),
            )
            if broker_order_id:
                connection.execute(
                    "UPDATE commands SET broker_order_id=COALESCE(broker_order_id, ?), updated_at=? WHERE command_id=?",
                    (broker_order_id, datetime.now().astimezone().isoformat(), link["submit_command_id"]),
                )
            return {
                "client_order_id": link["client_order_id"],
                "submit_command_id": link["submit_command_id"],
                "broker_client_order_id": broker_client_order_id or "",
            }

        candidates = []
        for candidate in connection.execute(
            """
            SELECT c.*
            FROM commands c
            LEFT JOIN order_links l ON l.client_order_id = c.client_order_id
            WHERE c.command_type = 'ORDER_SUBMIT'
              AND c.status IN ('ACKED', 'CLAIMED', 'DISPATCHING')
              AND c.client_order_id IS NOT NULL
              AND (l.client_order_id IS NULL OR l.broker_order_id IS NULL)
            ORDER BY c.created_at
            """
        ):
            if _matches(candidate, normalized):
                candidates.append(candidate)
        if len(candidates) > 1:
            raise AmbiguousOrderLinkError(
                f"broker order could not be uniquely associated: candidates={len(candidates)}"
            )
        if not candidates:
            return None
        candidate = candidates[0]
        local_client_order_id = candidate["client_order_id"]
        now = datetime.now().astimezone().isoformat()
        connection.execute(
            """
            INSERT INTO order_links(
                client_order_id, submit_command_id, broker_client_order_id,
                broker_order_id, exchange_order_id, last_broker_status,
                last_raw_status, origin, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?, 'SYSTEM', ?, ?)
            ON CONFLICT(client_order_id) DO UPDATE SET
                submit_command_id = excluded.submit_command_id,
                broker_client_order_id = excluded.broker_client_order_id,
                broker_order_id = excluded.broker_order_id,
                exchange_order_id = COALESCE(excluded.exchange_order_id, order_links.exchange_order_id),
                updated_at = excluded.updated_at
            """,
            (
                local_client_order_id,
                candidate["command_id"],
                broker_client_order_id,
                broker_order_id,
                normalized.get("exchange_order_id"),
                normalized.get("status"),
                normalized.get("raw_status"),
                now,
                now,
            ),
        )
        if broker_order_id:
            connection.execute(
                "UPDATE commands SET broker_order_id=COALESCE(broker_order_id, ?), updated_at=? WHERE command_id=?",
                (broker_order_id, now, candidate["command_id"]),
            )
        return {
            "client_order_id": local_client_order_id,
            "submit_command_id": candidate["command_id"],
            "broker_client_order_id": broker_client_order_id or "",
        }

"""SDK-side complete snapshot collection; no file or database access.

Call on the SDK callback thread. This module has no side effects on import.
"""
from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from broker_node.gm_agent.gm_mapper import map_account, map_fill, map_order, map_position


class SnapshotCollectionError(RuntimeError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping) or hasattr(value, 'items'):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SnapshotCollectionError('non-string SDK data key')
            result[key] = _json_value(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise SnapshotCollectionError('non-finite SDK decimal')
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise SnapshotCollectionError('non-finite SDK float')
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SnapshotCollectionError('unsupported SDK data type: ' + type(value).__name__)


def _separate_broker_id(mapped: dict[str, Any]) -> dict[str, Any]:
    normalized = mapped['normalized']
    normalized['broker_client_order_id'] = normalized['client_order_id']
    normalized['client_order_id'] = None
    return mapped


def collect_snapshot(adapter: Any, expected_account_id: str) -> dict[str, Any]:
    if not isinstance(expected_account_id, str) or not expected_account_id:
        raise SnapshotCollectionError('expected account ID required')
    if adapter.account_id() != expected_account_id:
        raise SnapshotCollectionError('account identity mismatch')
    if adapter.account().status.get('state') != 3:
        raise SnapshotCollectionError('account is not logged in')
    cash = adapter.cash()
    account = map_account(cash)
    if str(account['normalized']['account_id']) != expected_account_id:
        raise SnapshotCollectionError('cash account identity mismatch')
    # Every SDK call must succeed; do not turn None, exceptions, or partial
    # collections into empty results. No slicing or sampling is permitted.
    positions = [map_position(item) for item in adapter.positions()]
    orders = [_separate_broker_id(map_order(item)) for item in adapter.orders()]
    unfinished = [_separate_broker_id(map_order(item)) for item in adapter.unfinished_orders()]
    fills = [_separate_broker_id(map_fill(item)) for item in adapter.execution_reports()]
    if adapter.account_id() != expected_account_id or adapter.account().status.get('state') != 3:
        raise SnapshotCollectionError('account changed or disconnected during query')
    batch = {
        'batch_id': str(uuid.uuid4()), 'as_of': datetime.now(timezone.utc).isoformat(),
        'account': account, 'positions': positions, 'orders': orders,
        'unfinished_orders': unfinished, 'fills': fills,
        'component_counts': {'positions': len(positions), 'orders': len(orders),
                             'unfinished_orders': len(unfinished), 'fills': len(fills)},
    }
    return _json_value(batch)

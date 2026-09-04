from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BrokerNotConnectedError(RuntimeError):
    """Raised when a broker operation is requested before an adapter is connected."""


class BrokerGateway(ABC):
    @abstractmethod
    def connect(self) -> dict[str, Any]: ...

    @abstractmethod
    def get_capabilities(self) -> dict[str, Any]: ...

    @abstractmethod
    def get_account(self) -> dict[str, Any]: ...

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_orders(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_fills(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def submit_order(self, order: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> dict[str, Any]: ...


class DisconnectedBrokerGateway(BrokerGateway):
    """Explicit pre-connection gateway; it never creates fake broker data."""

    def _not_connected(self) -> None:
        raise BrokerNotConnectedError("Broker Gateway is not connected; configure a broker adapter before this operation")

    def connect(self) -> dict[str, Any]:
        return {"status": "DISCONNECTED", "message": "未配置券商连接"}

    def get_capabilities(self) -> dict[str, Any]:
        return {"status": "DISCONNECTED", "native_orders": [], "conditional_execution": [], "algorithms": []}

    def get_account(self) -> dict[str, Any]:
        self._not_connected()

    def get_positions(self) -> list[dict[str, Any]]:
        self._not_connected()

    def get_orders(self) -> list[dict[str, Any]]:
        self._not_connected()

    def get_fills(self) -> list[dict[str, Any]]:
        self._not_connected()

    def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        self._not_connected()

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        self._not_connected()

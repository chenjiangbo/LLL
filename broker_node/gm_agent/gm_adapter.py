from __future__ import annotations

from pathlib import Path
from typing import Any


class GmAdapterError(RuntimeError):
    pass


class GmContextAdapter:
    """Adapter around the verified gm.api context.

    This module is imported only by the GM Strategy Agent process.
    """

    def __init__(self, context: Any):
        self.context = context
        self._account = context.account()
        if self._account is None:
            raise GmAdapterError("gm.api returned no account object")
        if getattr(self._account, "status", {}).get("state") != 3:
            raise GmAdapterError("gm.api account is not LOGGEDIN state=3")

    def account(self) -> Any:
        return self._account

    def account_id(self) -> str:
        """Return the broker account id from the verified gm.api account data.

        Guotou's bundled gm.api Account object does not expose account_id on the
        object itself; the same official account query exposes it in cash.
        """
        account_id = getattr(self._account, "account_id", None)
        if account_id:
            return str(account_id)
        cash = getattr(self._account, "cash", None)
        if isinstance(cash, dict) and cash.get("account_id"):
            return str(cash["account_id"])
        raise GmAdapterError("gm.api account data has no account_id")

    def cash(self) -> Any:
        cash = getattr(self._account, "cash", None)
        if cash is None:
            raise GmAdapterError("gm.api account data has no cash")
        return cash

    def positions(self) -> list[Any]:
        return list(self._account.positions())

    def orders(self) -> list[Any]:
        from gm.api import get_orders
        return list(get_orders())

    def unfinished_orders(self) -> list[Any]:
        from gm.api import get_unfinished_orders
        return list(get_unfinished_orders())

    def execution_reports(self) -> list[Any]:
        from gm.api import get_execution_reports
        return list(get_execution_reports())

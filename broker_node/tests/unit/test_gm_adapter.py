from types import SimpleNamespace

from broker_node.gm_agent.gm_adapter import GmContextAdapter


def test_account_id_comes_from_cash_for_guotou_account_shape():
    account = SimpleNamespace(
        status={"state": 3},
        cash={"account_id": "gm-account-id"},
    )
    context = SimpleNamespace(account=lambda: account)

    assert GmContextAdapter(context).account_id() == "gm-account-id"
    assert GmContextAdapter(context).cash() == {"account_id": "gm-account-id"}

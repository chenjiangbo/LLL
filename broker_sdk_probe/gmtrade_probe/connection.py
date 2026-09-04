import importlib


def login_readonly(config):
    api = importlib.import_module("gmtrade.api")
    api.set_token(config["gm_token"])
    api.set_endpoint(config["endpoint"])
    account = api.account(account_id=config["gmtrade_account_id"])
    api.login(account)
    return api, account

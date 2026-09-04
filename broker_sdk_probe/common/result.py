import datetime as dt


def result(status, **details):
    return {"status": status, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(), **details}

import importlib
import importlib.metadata
import inspect


def inspect_surface():
    report = {"import": "FAIL", "package_version": None, "modules": {}, "errors": []}
    try:
        package = importlib.import_module("gmtrade")
        report["import"] = "PASS"
        try:
            report["package_version"] = importlib.metadata.version("gmtrade")
        except importlib.metadata.PackageNotFoundError as exc:
            report["errors"].append({"stage": "version", "type": type(exc).__name__, "text": str(exc)})
        for module_name in ("gmtrade.api", "gmtrade.api.trade", "gmtrade.api.callback", "gmtrade.api.storage"):
            try:
                module = importlib.import_module(module_name)
                names = {}
                for name in sorted(item for item in dir(module) if not item.startswith("_")):
                    item = getattr(module, name)
                    if callable(item):
                        try:
                            names[name] = str(inspect.signature(item))
                        except (TypeError, ValueError):
                            names[name] = "<signature unavailable>"
                report["modules"][module_name] = {"import": "PASS", "callables": names}
            except Exception as exc:
                report["modules"][module_name] = {"import": "FAIL", "error": {"type": type(exc).__name__, "text": str(exc)}}
                report["errors"].append({"stage": module_name, "type": type(exc).__name__, "text": str(exc)})
    except Exception as exc:
        report["errors"].append({"stage": "gmtrade", "type": type(exc).__name__, "text": str(exc)})
    return report

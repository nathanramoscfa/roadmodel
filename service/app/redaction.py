"""Process hooks with request-local state; records leave no live secret objects.

Install before importing provider SDKs. Previously saved aliases of warnings.warn
can bypass the pre-registry hook; qualified SDK warning calls are covered.
"""

from __future__ import annotations

import logging
import re
import traceback
import warnings
from contextvars import ContextVar
from typing import Any, Final

REDACTED: Final = "[visitor-key]"
_VISITOR_KEY: ContextVar[str | None] = getattr(
    logging.Logger.makeRecord, "_roadmodel_visitor_context", None
) or ContextVar("roadmodel_visitor_key", default=None)
_KEY_SHAPES = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,}")
_SENSITIVE_FIELDS = frozenset(
    {"authorization", "api_key", "apikey", "x-api-key", "x-roadmodel-visitor-key"}
)
_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}
_ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'
_PUBLIC_ROUTES = frozenset(
    {
        "/healthz",
        "/v1/recommend",
        "/v1/recommend/ladder",
        "/v1/visitor/recommend/ladder",
        "/v1/score",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)


def scrub(text: str) -> str:
    key = _VISITOR_KEY.get()
    if key:
        replacement = "[redacted]" if key == REDACTED else REDACTED
        if replacement in key:
            text = text.replace(key, replacement)
        else:
            text = replacement.join(
                part.replace(key, replacement) for part in text.split(replacement)
            )
    return _KEY_SHAPES.sub(REDACTED, text)


def _text(value: object) -> str:
    try:
        return scrub(str(value))[:65536]
    except Exception:
        return "[unprintable diagnostic]"


def _clean(value: object, seen: set[int], depth: int = 0) -> Any:
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, int | float):
        try:
            return int(value) if isinstance(value, int) else float(value)
        except Exception:
            return REDACTED
    if isinstance(value, str):
        return _text(value)
    if depth >= 8 or id(value) in seen:
        return "[bounded diagnostic]"
    seen.add(id(value))
    try:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 128:
                    result["[remaining]"] = "[bounded diagnostic]"
                    break
                name = _text(key)
                result[name] = (
                    REDACTED if name.lower() in _SENSITIVE_FIELDS else _clean(item, seen, depth + 1)
                )
            return result
        if isinstance(value, list | tuple):
            items = [_clean(item, seen, depth + 1) for item in value[:128]]
            if len(value) > 128:
                items.append("[bounded diagnostic]")
            return tuple(items) if isinstance(value, tuple) else items
        return _text(value)
    finally:
        seen.remove(id(value))


def _scrub_record(record: logging.LogRecord) -> None:
    access = (
        record.msg == _ACCESS_FORMAT
        and isinstance(record.args, tuple)
        and len(record.args) == 5
        and type(record.args[4]) is int
    )
    if access and isinstance(record.args, tuple):
        # The installed Uvicorn AccessFormatter consumes this five-field tuple.
        # Preserve its fixed format, while omitting addresses and query strings.
        _, method, path, version, status = record.args
        route = str(path).partition("?")[0]
        record.args = (
            "[client]",
            method
            if method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
            else "[method]",
            route if route in _PUBLIC_ROUTES else "[route]",
            version if version in {"1.0", "1.1", "2", "2.0", "3"} else "[version]",
            status,
        )
    else:
        try:
            record.args = _clean(record.args, set())
            record.msg = scrub(record.getMessage())
        except Exception:
            record.msg = REDACTED
        record.args = ()
    if record.exc_info:
        try:
            record.exc_text = scrub("".join(traceback.format_exception(*record.exc_info)))
        except Exception:
            record.exc_text = "[unprintable exception]"
        record.exc_info = None
    # makeRecord adds `extra` AFTER calling the record factory. Never trust a
    # caller-provided scrubbed flag; sanitize the fully populated record.
    clean: dict[str, Any] = {}
    extras = 0
    for name, value in record.__dict__.items():
        if name not in _RECORD_FIELDS:
            extras += 1
            if extras > 128:
                continue
        field = name if name in _RECORD_FIELDS else _text(name)
        clean[field] = REDACTED if field.lower() in _SENSITIVE_FIELDS else _clean(value, set())
    record.__dict__.clear()
    record.__dict__.update(clean)
    if access:
        record.msg = _ACCESS_FORMAT


class VisitorKeyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        _scrub_record(record)
        return True


_FILTER = VisitorKeyFilter()


def install_redaction() -> None:
    previous = logging.Logger.makeRecord
    if not getattr(previous, "_roadmodel_visitor_context", None):

        def make_record(self: logging.Logger, *args: Any, **kwargs: Any) -> logging.LogRecord:
            record = previous(self, *args, **kwargs)
            _scrub_record(record)
            return record

        make_record._roadmodel_visitor_context = _VISITOR_KEY  # type: ignore[attr-defined]
        logging.Logger.makeRecord = make_record  # type: ignore[method-assign]

    previous_filter = logging.Filterer.filter
    if not getattr(previous_filter, "_roadmodel_redaction", False):

        def filtered(self: logging.Filterer, record: logging.LogRecord) -> Any:
            result = previous_filter(self, record)
            if result:
                _scrub_record(result if isinstance(result, logging.LogRecord) else record)
            return result

        filtered._roadmodel_redaction = True  # type: ignore[attr-defined]
        logging.Filterer.filter = filtered  # type: ignore[method-assign]

    root = logging.getLogger()
    root.addFilter(_FILTER)
    for handler in root.handlers:
        handler.addFilter(_FILTER)

    previous_warn = warnings.warn
    if not getattr(previous_warn, "_roadmodel_redaction", False):

        def warn(
            message: Any,
            category: Any = None,
            stacklevel: int = 1,
            source: Any = None,
            **kwargs: Any,
        ) -> None:
            diagnostic = str(message) + str(category or type(message))
            if scrub(diagnostic) != diagnostic:
                logging.getLogger(__name__).warning("sensitive provider warning suppressed")
                return
            if _VISITOR_KEY.get() and isinstance(message, Warning):
                category = type(message)
                message = str(message)
            previous_warn(
                message,
                category,
                stacklevel=stacklevel + 1,
                source=None if _VISITOR_KEY.get() else source,
                **kwargs,
            )

        warn._roadmodel_redaction = True  # type: ignore[attr-defined]
        warnings.warn = warn

    previous_explicit = warnings.warn_explicit
    if not getattr(previous_explicit, "_roadmodel_redaction", False):

        def warn_explicit(
            message: Any, category: Any, filename: str, lineno: int, *args: Any, **kwargs: Any
        ) -> None:
            diagnostic = str(message) + str(category) + filename + str(kwargs.get("module", ""))
            if args:
                diagnostic += str(args[0])
            if scrub(diagnostic) != diagnostic:
                logging.getLogger(__name__).warning("sensitive provider warning suppressed")
                return
            if _VISITOR_KEY.get():
                # Allocation diagnostics can retain arbitrary request objects.
                if isinstance(message, Warning):
                    category = type(message)
                    message = str(message)
                kwargs.pop("source", None)
                if len(args) >= 4:
                    args = (*args[:3], None, *args[4:])
            previous_explicit(message, category, filename, lineno, *args, **kwargs)

        warn_explicit._roadmodel_redaction = True  # type: ignore[attr-defined]
        warnings.warn_explicit = warn_explicit

    previous_show = warnings.showwarning
    if not getattr(previous_show, "_roadmodel_redaction", False):
        # captureWarnings delegates explicit file output to its mutable saved
        # hook. Never capture that delegating function in our wrapper: toggling
        # capture later can otherwise make the two hooks call each other.
        capture = previous_show is getattr(logging, "_showwarning", None)
        base_show: Any = (
            getattr(logging, "_warnings_showwarning", None) if capture else previous_show
        )
        seen_sinks: set[int] = set()
        while getattr(base_show, "_roadmodel_showwarning_base", None) is not None:
            if id(base_show) in seen_sinks:
                base_show = None
                break
            seen_sinks.add(id(base_show))
            base_show = base_show._roadmodel_showwarning_base
        if base_show is None or base_show is getattr(logging, "_showwarning", None):
            base_show = warnings._showwarning_orig  # type: ignore[attr-defined]

        def showwarning(
            message: Any,
            category: Any,
            filename: str,
            lineno: int,
            file: Any = None,
            line: str | None = None,
        ) -> None:
            safe_category = UserWarning if scrub(str(category)) != str(category) else category
            safe_message, safe_filename = scrub(str(message)), scrub(filename)
            safe_line = scrub(line) if line else ""
            if capture and file is None:
                text = warnings.formatwarning(
                    safe_message, safe_category, safe_filename, lineno, line=safe_line
                )
                logging.getLogger("py.warnings").warning("%s", text)
            else:
                base_show(
                    safe_message, safe_category, safe_filename, lineno, file=file, line=safe_line
                )

        showwarning._roadmodel_redaction = True  # type: ignore[attr-defined]
        showwarning._roadmodel_showwarning_base = base_show  # type: ignore[attr-defined]
        warnings.showwarning = showwarning

    previous_capture = logging.captureWarnings
    if not getattr(previous_capture, "_roadmodel_redaction", False):

        def capture_warnings(capture: bool) -> None:
            previous_capture(capture)
            # captureWarnings(False) restores a saved sink. Keep that sink's
            # semantics, but reinstall sanitization after either transition.
            install_redaction()

        capture_warnings._roadmodel_redaction = True  # type: ignore[attr-defined]
        logging.captureWarnings = capture_warnings


install_redaction()

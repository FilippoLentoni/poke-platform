from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

try:
    from langfuse import get_client, propagate_attributes
except Exception:  # pragma: no cover
    get_client = None  # type: ignore
    propagate_attributes = None  # type: ignore


def _client():
    if get_client is None:
        return None
    try:
        return get_client()
    except Exception:
        return None


@contextmanager
def trace_invocation(
    *,
    name: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    input: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[None]:
    """
    Create a top-level trace for one agent invocation.
    Falls back to a no-op context manager if Langfuse is unavailable.
    """
    client = _client()
    if client is None:
        yield
        return

    attrs_ctx = (
        propagate_attributes(
            user_id=user_id,
            session_id=session_id,
            metadata=metadata,
        )
        if propagate_attributes is not None
        else None
    )
    try:
        if attrs_ctx is not None:
            attrs_ctx.__enter__()
    trace_context = {"trace_id": client.create_trace_id()}
    with client.start_as_current_observation(
        trace_context=trace_context,
        name=name,
        as_type="agent",
        input=input,
        metadata=metadata,
    ):
        yield
    finally:
        if attrs_ctx is not None:
            attrs_ctx.__exit__(None, None, None)


@contextmanager
def trace_step(
    *,
    name: str,
    as_type: str = "span",
    input: Optional[Any] = None,
    output: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
    level: Optional[str] = None,
) -> Iterator[None]:
    """
    Create a named observation for a reasoning step.
    """
    client = _client()
    if client is None:
        yield
        return

    with client.start_as_current_observation(
        name=name,
        as_type=as_type,
        input=input,
        output=output,
        metadata=metadata,
        level=level,
    ):
        yield


def update_trace(
    *,
    name: Optional[str] = None,
    input: Optional[Any] = None,
    output: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.update_current_trace(
            name=name,
            input=input,
            output=output,
            metadata=metadata,
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:
        pass


def score_trace(
    *,
    name: str,
    value: float | str,
    data_type: Optional[str] = None,
    comment: Optional[str] = None,
    config_id: Optional[str] = None,
) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.score_current_trace(
            name=name,
            value=value,
            data_type=data_type,
            comment=comment,
            config_id=config_id,
        )
    except Exception:
        pass


def score_span(
    *,
    name: str,
    value: float | str,
    data_type: Optional[str] = None,
    comment: Optional[str] = None,
    config_id: Optional[str] = None,
) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.score_current_span(
            name=name,
            value=value,
            data_type=data_type,
            comment=comment,
            config_id=config_id,
        )
    except Exception:
        pass

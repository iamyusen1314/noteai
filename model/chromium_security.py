"""Fail-closed Chromium launch helpers shared by NoteAI browser workers."""

from __future__ import annotations

from typing import Any


FORBIDDEN_CHROMIUM_FLAGS = frozenset({
    "--disable-setuid-sandbox",
    "--no-sandbox",
    "--no-zygote",
})


def _sandboxed_launch_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return launch options that require Chromium's sandbox.

    The helper rejects sandbox-bypass flags before Playwright receives them and
    never retries a failed sandboxed launch with weaker settings.
    """
    launch_kwargs = dict(kwargs)
    if launch_kwargs.get("chromium_sandbox", True) is not True:
        raise ValueError("Chromium sandbox must remain enabled")

    args = launch_kwargs.get("args") or ()
    forbidden = sorted({
        str(arg).split("=", 1)[0].strip().lower()
        for arg in args
        if str(arg).split("=", 1)[0].strip().lower() in FORBIDDEN_CHROMIUM_FLAGS
    })
    if forbidden:
        raise ValueError(f"Forbidden Chromium sandbox bypass flags: {', '.join(forbidden)}")

    launch_kwargs["chromium_sandbox"] = True
    return launch_kwargs


def launch_chromium(chromium: Any, **kwargs: Any) -> Any:
    """Launch a synchronous Chromium instance with sandbox enforcement."""
    return chromium.launch(**_sandboxed_launch_kwargs(kwargs))


async def launch_chromium_async(chromium: Any, **kwargs: Any) -> Any:
    """Launch an asynchronous Chromium instance with sandbox enforcement."""
    return await chromium.launch(**_sandboxed_launch_kwargs(kwargs))

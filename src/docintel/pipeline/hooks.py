"""The 8 hook sockets.

A domain pack must be able to customize every pipeline stage without forking the
pipeline. A bug in pack code must never take down the run. Middleware chains work
like Express.js: each hook receives the context and a next(). It can transform
and pass along, stop the chain by not calling next(), or throw — in which case
the document goes to the dead-letter queue and the run continues (spec Part 4).
"""

from __future__ import annotations

from collections.abc import Callable

from docintel.core.errors import PackError
from docintel.core.models import JobContext

SOCKETS: tuple[str, ...] = (
    "beforeIntake",
    "afterFilter",
    "classifySignals",
    "beforePersonaLookup",
    "afterExtraction",
    "beforeConfidenceGate",
    "beforeEmit",
    "onRegenTrigger",
)

Next = Callable[[JobContext], JobContext]
HookFn = Callable[[JobContext, Next], JobContext]


class HookRegistry:
    def __init__(self) -> None:
        self._chains: dict[str, list[tuple[str, HookFn]]] = {s: [] for s in SOCKETS}

    def register(self, socket: str, fn: HookFn, pack: str) -> None:
        if socket not in self._chains:
            raise ValueError(f"unknown socket {socket!r}; expected one of {list(SOCKETS)}")
        self._chains[socket].append((pack, fn))

    def registered(self, socket: str) -> list[str]:
        return [f"{pack}.{fn.__name__}" for pack, fn in self._chains[socket]]

    def run(self, socket: str, ctx: JobContext) -> JobContext:
        chain = tuple(self._chains[socket])
        if not chain:
            return ctx

        def step(index: int) -> Next:
            def call(c: JobContext) -> JobContext:
                if index >= len(chain):
                    return c

                pack, fn = chain[index]
                next_fn = step(index + 1)
                called = [False]  # Use list for mutability in closure

                def tracked_next(c2: JobContext) -> JobContext:
                    if called[0]:
                        raise PackError(
                            f"hook {pack}.{fn.__name__} at socket {socket!r} called next() more than once"
                        )
                    called[0] = True
                    return next_fn(c2)

                try:
                    result = fn(c, tracked_next)
                    if not isinstance(result, JobContext):
                        raise PackError(
                            f"hook {pack}.{fn.__name__} at socket {socket!r} returned {type(result).__name__!r}, expected JobContext"
                        )
                    return result
                except PackError:
                    raise
                except Exception as exc:
                    raise PackError(
                        f"hook {pack}.{fn.__name__} at socket {socket!r} raised: {exc}"
                    ) from exc

            return call

        return step(0)(ctx)

import pytest
from docintel.core.errors import PackError
from docintel.core.models import new_context
from docintel.pipeline.hooks import SOCKETS, HookRegistry


def test_eight_sockets_exactly():
    assert SOCKETS == (
        "beforeIntake", "afterFilter", "classifySignals", "beforePersonaLookup",
        "afterExtraction", "beforeConfidenceGate", "beforeEmit", "onRegenTrigger",
    )


def test_registering_an_unknown_socket_fails_loudly():
    reg = HookRegistry()
    with pytest.raises(ValueError, match="unknown socket"):
        reg.register("afterLunch", lambda ctx, nxt: nxt(ctx), pack="test")


def test_chain_runs_in_registration_order():
    reg = HookRegistry()

    def a(ctx, nxt):
        ctx.log("a")
        return nxt(ctx)

    def b(ctx, nxt):
        ctx.log("b")
        return nxt(ctx)

    reg.register("afterFilter", a, pack="p1")
    reg.register("afterFilter", b, pack="p1")
    ctx = reg.run("afterFilter", new_context("d", "/x.pdf"))
    assert ctx.events == ["a", "b"]


def test_hook_can_short_circuit_by_not_calling_next():
    reg = HookRegistry()
    reg.register("afterFilter", lambda ctx, nxt: ctx, pack="p1")
    reg.register("afterFilter", lambda ctx, nxt: (ctx.log("never"), nxt(ctx))[1], pack="p1")
    ctx = reg.run("afterFilter", new_context("d", "/x.pdf"))
    assert ctx.events == []


def test_a_throwing_hook_raises_PackError_naming_the_pack():
    """Spec Part 4: a throwing hook never crashes the run; the runner routes it to the DLQ."""
    reg = HookRegistry()

    def boom(ctx, nxt):
        raise RuntimeError("pack bug")

    reg.register("afterExtraction", boom, pack="northstar")
    with pytest.raises(PackError, match="northstar"):
        reg.run("afterExtraction", new_context("d", "/x.pdf"))


def test_empty_socket_is_a_no_op():
    reg = HookRegistry()
    ctx_in = new_context("d", "/x.pdf")
    assert reg.run("beforeEmit", ctx_in) is ctx_in


def test_registered_reports_pack_qualified_names():
    reg = HookRegistry()
    reg.register("beforeEmit", lambda ctx, nxt: nxt(ctx), pack="northstar")
    assert reg.registered("beforeEmit") == ["northstar.<lambda>"]

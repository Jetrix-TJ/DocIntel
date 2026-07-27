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


def test_hook_returning_none_raises_PackError():
    """A hook that forgets return() yields None; must be wrapped as PackError."""
    reg = HookRegistry()

    def buggy(ctx, nxt):
        pass  # implicitly returns None

    reg.register("afterFilter", buggy, pack="badpack")
    with pytest.raises(PackError, match="badpack.*returned.*NoneType"):
        reg.run("afterFilter", new_context("d", "/x.pdf"))


def test_hook_returning_dict_raises_PackError():
    """A hook returning wrong type raises PackError."""
    reg = HookRegistry()

    def buggy(ctx, nxt):
        return {"data": "wrong type"}

    reg.register("afterFilter", buggy, pack="badpack")
    with pytest.raises(PackError, match="badpack.*returned.*dict"):
        reg.run("afterFilter", new_context("d", "/x.pdf"))


def test_hook_returning_str_raises_PackError():
    """A hook returning wrong type raises PackError."""
    reg = HookRegistry()

    def buggy(ctx, nxt):
        return "wrong type"

    reg.register("afterFilter", buggy, pack="badpack")
    with pytest.raises(PackError, match="badpack.*returned.*str"):
        reg.run("afterFilter", new_context("d", "/x.pdf"))


def test_hook_calling_next_twice_raises_PackError():
    """A hook that calls next() twice re-executes downstream; must be guarded."""
    reg = HookRegistry()

    def double_call(ctx, nxt):
        nxt(ctx)
        return nxt(ctx)  # second call on same next()

    reg.register("afterFilter", double_call, pack="badpack")
    with pytest.raises(PackError, match="badpack.*double_call.*called next.*more than once"):
        reg.run("afterFilter", new_context("d", "/x.pdf"))


def test_hook_registering_mid_dispatch_does_not_affect_current_run():
    """Registering a hook mid-dispatch must not splice it into the running chain."""
    reg = HookRegistry()

    def first(ctx, nxt):
        ctx.log("first")
        return nxt(ctx)

    def registrar(ctx, nxt):
        def third(c, n):
            c.log("third")
            return n(c)
        reg.register("afterFilter", third, pack="p1")
        ctx.log("registrar")
        return nxt(ctx)

    reg.register("afterFilter", first, pack="p1")
    reg.register("afterFilter", registrar, pack="p1")

    ctx = reg.run("afterFilter", new_context("d", "/x.pdf"))
    # Current run should be only first, registrar (not third)
    assert ctx.events == ["first", "registrar"]

    # Next run should include the newly registered third hook
    ctx2 = reg.run("afterFilter", new_context("d", "/y.pdf"))
    assert ctx2.events == ["first", "registrar", "third"]


def test_MemoryError_is_wrapped_as_PackError():
    """MemoryError must be caught and wrapped, not propagate raw."""
    reg = HookRegistry()

    def oom(ctx, nxt):
        raise MemoryError("out of memory")

    reg.register("afterFilter", oom, pack="mempack")
    with pytest.raises(PackError, match="mempack.*oom"):
        reg.run("afterFilter", new_context("d", "/x.pdf"))


def test_KeyboardInterrupt_propagates_raw():
    """KeyboardInterrupt must NOT be wrapped; allows Ctrl-C to work."""
    reg = HookRegistry()

    def interrupted(ctx, nxt):
        raise KeyboardInterrupt()

    reg.register("afterFilter", interrupted, pack="p1")
    with pytest.raises(KeyboardInterrupt):
        reg.run("afterFilter", new_context("d", "/x.pdf"))


def test_hook_passing_different_context_to_next_still_works():
    """A hook can substitute a different context and pass it downstream."""
    reg = HookRegistry()

    def substitute(ctx, nxt):
        # Replace context with a new one
        new_ctx = new_context("different_doc", "/y.pdf")
        new_ctx.log("substituted")
        return nxt(new_ctx)

    def downstream(ctx, nxt):
        ctx.log("downstream")
        return nxt(ctx)

    reg.register("afterFilter", substitute, pack="p1")
    reg.register("afterFilter", downstream, pack="p1")

    ctx = reg.run("afterFilter", new_context("d", "/x.pdf"))
    assert ctx.events == ["substituted", "downstream"]
    # The returned context should be from substitution, not original
    assert ctx.document_id == "different_doc"

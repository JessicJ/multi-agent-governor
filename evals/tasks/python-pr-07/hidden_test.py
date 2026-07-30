from pluggy import HookimplMarker, HookspecMarker, PluginManager


hookspec = HookspecMarker("magov")
hookimpl = HookimplMarker("magov")


def test_removing_one_plugin_clears_all_of_its_implementations() -> None:
    manager = PluginManager("magov")

    class Spec:
        @hookspec
        def hello(self, value: int) -> int: ...

    class Plugin:
        @hookimpl
        def hello(self, value: int) -> int:
            return value + 1

        @hookimpl(specname="hello")
        def another_hello(self, value: int) -> int:
            return value + 100

    manager.add_hookspecs(Spec)
    plugin = Plugin()
    manager.register(plugin)

    caller = manager.hook.hello
    caller._remove_plugin(plugin)

    assert caller.get_hookimpls() == []
    assert caller(value=1) == []


def test_get_hookcallers_deduplicates_multiple_implementations() -> None:
    manager = PluginManager("magov")

    class Spec:
        @hookspec
        def hello(self, value: int) -> int: ...

        @hookspec
        def goodbye(self, value: int) -> int: ...

    class Plugin:
        @hookimpl
        def hello(self, value: int) -> int:
            return value + 1

        @hookimpl(specname="hello")
        def another_hello(self, value: int) -> int:
            return value + 100

        @hookimpl
        def goodbye(self, value: int) -> int:
            return value + 200

    manager.add_hookspecs(Spec)
    plugin = Plugin()
    manager.register(plugin)

    callers = manager.get_hookcallers(plugin)

    assert callers is not None
    assert {caller.name for caller in callers} == {"hello", "goodbye"}
    assert len(callers) == 2

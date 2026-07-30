import pytest


@pytest.mark.parametrize("historic", [False, True])
def test_register_while_calling(historic: bool) -> None:
    from pluggy import HookimplMarker
    from pluggy import HookspecMarker
    from pluggy import PluginManager

    hookspec = HookspecMarker("example")
    hookimpl = HookimplMarker("example")
    manager = PluginManager("example")

    class Hooks:
        @hookspec(historic=historic)
        def configure(self) -> int:
            raise NotImplementedError()

    class Plugin1:
        @hookimpl
        def configure(self) -> int:
            return 1

    class Plugin2:
        def __init__(self) -> None:
            self.already_registered = False

        @hookimpl
        def configure(self) -> int:
            if not self.already_registered:
                manager.register(Plugin4())
                manager.register(Plugin5())
                manager.register(Plugin6())
                self.already_registered = True
            return 2

    class Plugin3:
        @hookimpl
        def configure(self) -> int:
            return 3

    class Plugin4:
        @hookimpl(tryfirst=True)
        def configure(self) -> int:
            return 4

    class Plugin5:
        @hookimpl
        def configure(self) -> int:
            return 5

    class Plugin6:
        @hookimpl(trylast=True)
        def configure(self) -> int:
            return 6

    manager.add_hookspecs(Hooks)
    manager.register(Plugin1())
    manager.register(Plugin2())
    manager.register(Plugin3())

    if historic:
        first: list[int] = []
        manager.hook.configure.call_historic(first.append)
        assert first == [4, 5, 6, 3, 2, 1]
        second: list[int] = []
        manager.hook.configure.call_historic(second.append)
        assert second == [4, 5, 3, 2, 1, 6]
    else:
        assert manager.hook.configure() == [3, 2, 1]
        assert manager.hook.configure() == [4, 5, 3, 2, 1, 6]

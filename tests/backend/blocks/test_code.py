import sys
import types

import pytest
from writer.blocks.code import CodeBlock


def test_run_code(session, runner, monkeypatch):
    fake_module = types.ModuleType("fake_writeruserapp")
    fake_module.my_fn = lambda: "Monkeypatched!"
    monkeypatch.setitem(sys.modules, "writeruserapp", fake_module)
    component = session.add_fake_component(
        {
            "code": """
print('hi testing stdout ' + str(test_thing_ee) + my_fn())
set_output("return " + str(test_thing_ee))
"""
        }
    )
    block = CodeBlock(component, runner, {"test_thing_ee": 26})
    block.run()
    assert block.outcome == "success"
    assert block.result == "return 26"


def test_run_invalid_code(session, runner, monkeypatch):
    fake_module = types.ModuleType("fake_writeruserapp")
    fake_module.my_fn = lambda: "Monkeypatched!"
    monkeypatch.setitem(sys.modules, "writeruserapp", fake_module)

    component = session.add_fake_component(
        {
            "code": """
print(1/0)
"""
        }
    )
    block = CodeBlock(component, runner, {})
    with pytest.raises(ZeroDivisionError):
        block.run()
    assert block.outcome == "error"


def test_template_values_are_not_spliced_into_code(session, runner, monkeypatch):
    monkeypatch.setitem(sys.modules, "writeruserapp", types.ModuleType("fake_writeruserapp"))
    injection = '") ; state["pwned"] = True ; set_output("'
    component = session.add_fake_component(
        {
            "code": """
greeting = "Hello @{payload}"
set_output([greeting, @{payload}, '''@{payload}'''])
"""
        }
    )
    block = CodeBlock(component, runner, {"payload": injection})
    block.run()
    assert block.outcome == "success"
    assert block.result == ["Hello " + injection, injection, injection]
    assert "pwned" not in session.session_state

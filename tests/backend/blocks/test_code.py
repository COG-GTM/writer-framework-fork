import sys
import types

import pytest
from writer.blocks.code import CodeBlock
from writer.ss_types import WriterConfigurationError


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


def test_template_in_case_pattern_rejected(session, runner, monkeypatch):
    monkeypatch.setitem(sys.modules, "writeruserapp", types.ModuleType("fake_writeruserapp"))
    component = session.add_fake_component({
        "code": 'match payload:\n    case "@{payload}":\n        set_output(1)\n'
    })
    block = CodeBlock(component, runner, {"payload": "yes"})
    with pytest.raises(WriterConfigurationError):
        block.run()
    assert block.outcome == "error"


def test_template_in_docstring_rejected(session, runner, monkeypatch):
    monkeypatch.setitem(sys.modules, "writeruserapp", types.ModuleType("fake_writeruserapp"))
    component = session.add_fake_component({
        "code": 'def task():\n    "Task: @{payload}"\n    return 1\nset_output(task())\n'
    })
    block = CodeBlock(component, runner, {"payload": "ship"})
    with pytest.raises(WriterConfigurationError):
        block.run()
    assert block.outcome == "error"


def test_case_named_variable_and_guard(session, runner, monkeypatch):
    monkeypatch.setitem(sys.modules, "writeruserapp", types.ModuleType("fake_writeruserapp"))
    component = session.add_fake_component({
        "code": (
            'case = "@{payload}"\n'
            'match case:\n'
            '    case str() if case == "@{payload}":\n'
            '        set_output([case, @{data}])\n'
        )
    })
    block = CodeBlock(component, runner, {"payload": "yes", "data": {1, 2}})
    block.run()
    assert block.result == ["yes", {1, 2}]

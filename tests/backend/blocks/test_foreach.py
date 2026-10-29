import json

import pytest

from writer.blocks.foreach import ForEach
from writer.ss_types import WriterConfigurationError


def test_basic_list(session, runner):
    component = session.add_fake_component({"items": "[2226, 2223]"})
    block = ForEach(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert 4 == block.result[0]
    assert 4 == block.result[1]


def test_basic_dict(session, runner):
    component = session.add_fake_component({"items": '{"a": "zzz", "b": "fff"}'})
    block = ForEach(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert 4 == block.result.get("a")
    assert 4 == block.result.get("b")


class RecordingRunner:
    def __init__(self, runner):
        self.calls = []
        self._runner = runner

    def install(self, monkeypatch):
        def record(base_component_id, base_outcome, execution_environments):
            self.calls.append(execution_environments)
            return len(execution_environments) * [4]

        monkeypatch.setattr(self._runner, "run_branch_batch", record)
        return self


def test_list_over_cap_raises_before_any_branch_runs(session, runner, monkeypatch):
    recorder = RecordingRunner(runner).install(monkeypatch)
    component = session.add_fake_component({"items": json.dumps(list(range(1001)))})
    block = ForEach(component, runner, {})
    with pytest.raises(WriterConfigurationError, match="1001 items"):
        block.run()
    assert block.outcome == "error"
    assert recorder.calls == []


def test_dict_over_cap_raises_before_any_branch_runs(session, runner, monkeypatch):
    recorder = RecordingRunner(runner).install(monkeypatch)
    items = {f"k{i}": i for i in range(1001)}
    component = session.add_fake_component({"items": json.dumps(items)})
    block = ForEach(component, runner, {})
    with pytest.raises(WriterConfigurationError, match="exceeds the maximum of 1000"):
        block.run()
    assert recorder.calls == []


def test_list_at_cap_runs(session, runner):
    component = session.add_fake_component({"items": json.dumps(list(range(1000)))})
    block = ForEach(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert len(block.result) == 1000


def test_cap_is_configurable(session, runner, monkeypatch):
    monkeypatch.setenv("WRITER_FOREACH_MAX_ITEMS", "2")
    component = session.add_fake_component({"items": "[1, 2, 3]"})
    block = ForEach(component, runner, {})
    with pytest.raises(WriterConfigurationError, match="maximum of 2"):
        block.run()

    component = session.add_fake_component({"items": "[1, 2]"}, id="ok_id")
    block = ForEach(component, runner, {})
    block.run()
    assert block.outcome == "success"


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
def test_invalid_cap_falls_back_to_default(session, runner, monkeypatch, raw):
    monkeypatch.setenv("WRITER_FOREACH_MAX_ITEMS", raw)
    component = session.add_fake_component({"items": json.dumps(list(range(1001)))})
    block = ForEach(component, runner, {})
    with pytest.raises(WriterConfigurationError, match="maximum of 1000"):
        block.run()


def test_fanout_is_passed_to_loop_branch(session, runner, monkeypatch):
    recorder = RecordingRunner(runner).install(monkeypatch)
    component = session.add_fake_component({"items": "[1, 2, 3]"})
    block = ForEach(component, runner, {"foreach_fanout": 4})
    block.run()
    assert [env["foreach_fanout"] for env in recorder.calls[0]] == [12, 12, 12]


def test_nested_loops_over_total_budget_raise(session, runner, monkeypatch):
    recorder = RecordingRunner(runner).install(monkeypatch)
    component = session.add_fake_component({"items": json.dumps(list(range(1000)))})
    block = ForEach(component, runner, {"foreach_fanout": 11})
    with pytest.raises(WriterConfigurationError, match="11000 iterations"):
        block.run()
    assert recorder.calls == []


def test_total_budget_is_configurable(session, runner, monkeypatch):
    monkeypatch.setenv("WRITER_FOREACH_MAX_TOTAL_ITERATIONS", "5")
    component = session.add_fake_component({"items": "[1, 2, 3]"})
    block = ForEach(component, runner, {"foreach_fanout": 2})
    with pytest.raises(WriterConfigurationError, match="6 iterations"):
        block.run()


def test_nested_for_each_through_real_runner(session, monkeypatch):
    from writer.blueprints import BlueprintRunner
    from writer.core_ui import Component

    monkeypatch.setenv("WRITER_FOREACH_MAX_TOTAL_ITERATIONS", "6")
    session.session_id = "foreach_test_session"
    session.add_fake_component({}, id="bp", type="blueprints_blueprint")
    outer = Component(
        id="outer",
        type="blueprints_foreach",
        parentId="bp",
        content={"items": "[1, 2, 3]"},
        outs=[{"toNodeId": "inner", "outId": "loop"}],
    )
    inner = Component(
        id="inner",
        type="blueprints_foreach",
        parentId="bp",
        content={"items": "[1, 2, 3]"},
        outs=[{"toNodeId": "leaf", "outId": "loop"}],
    )
    leaf = Component(
        id="leaf",
        type="blueprints_foreach",
        parentId="bp",
        content={"items": "[]"},
    )
    session.bmc_branch.attach(outer)
    session.bmc_branch.attach(inner)
    session.bmc_branch.attach(leaf)
    runner = BlueprintRunner(session)
    with pytest.raises(BaseException, match="Nested for-each loops would run 9 iterations"):
        runner.run_branch("outer", None, {})

    monkeypatch.setenv("WRITER_FOREACH_MAX_TOTAL_ITERATIONS", "9")
    runner.run_branch("outer", None, {})

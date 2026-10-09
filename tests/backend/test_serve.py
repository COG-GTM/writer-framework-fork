import json
import mimetypes
from typing import Any

import fastapi
import fastapi.testclient
import pytest
import writer.abstract
import writer.serve
from fastapi import FastAPI

from tests.backend import test_app_dir, test_multiapp_dir


def parse_sse_stream(response):
    """
    Utility function to parse SSE stream into list of (event, data) tuples.
    """
    events = []
    current_event = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: "):
            data = line[len("data: "):]
            if data == "[DONE]":
                break
            try:
                payload = json.loads(data)
                events.append((current_event, payload))
            except json.JSONDecodeError:
                continue
    return events


class TestServe:

    def test_valid(self) -> None:
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(
            test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.post("/api/init", json={
                "proposedSessionId": None
            }, headers={
                "Content-Type": "application/json"
            })
            assert res.status_code == 200
            session_id = res.json().get("sessionId")
            assert session_id is not None
            with client.websocket_connect("/api/stream") as websocket:
                websocket.send_json({
                    "type": "streamInit",
                    "trackingId": 0,
                    "payload": {
                        "sessionId": session_id
                    }
                })
                websocket.send_json({
                    "type": "event",
                    "trackingId": 1,
                    "payload": {
                        "type": "wf-number-change",
                        "instancePath": [
                            {"componentId": "root", "instanceNumber": 0}
                        ],
                        "payload": 9
                    }
                })
                a = websocket.receive_bytes()
                assert json.loads(a.decode()).get("messageType") == "eventResponse"
                websocket.close(1000)

    def test_bad_session(self) -> None:
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(
            test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            with client.websocket_connect("/api/stream") as websocket:
                websocket.send_json({
                    "type": "streamInit",
                    "trackingId": 0,
                    "payload": {
                        "sessionId": "bad_session"
                    }
                })
                with pytest.raises(fastapi.WebSocketDisconnect):
                    websocket.receive_bytes()

    def test_session_verifier_header(self) -> None:
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(
            test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.post("/api/init", json={
                "proposedSessionId": None
            }, headers={
                "Content-Type": "application/json",
                "X-Fail": "yes"
            })
            assert res.status_code == 403

    def test_session_verifier_cookies(self) -> None:
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(
            test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app, cookies={
            "fail_cookie": "yes"
        }) as client:
            res = client.post("/api/init", json={
                "proposedSessionId": None
            }, headers={
                "Content-Type": "application/json"
            })
            assert res.status_code == 403

    def test_session_verifier_pass(self) -> None:
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(
            test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app, cookies={
            "another_cookie": "yes"
        }) as client:
            res = client.post("/api/init", json={
                "proposedSessionId": None
            }, headers={
                "Content-Type": "application/json",
                "X-Success": "yes"
            })
            assert res.status_code == 200

    def test_serve_javascript_file_with_a_valid_content_type(self) -> None:
        # Arrange
        mimetypes.add_type("text/plain", ".js")

        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            # Acts
            res = client.get("/static/file.js")

            # Assert
            assert res.status_code == 200
            assert res.headers["Content-Type"].startswith("text/javascript")

    def test_multiapp_should_run_the_lifespan_of_all_writer_app(self):
        """
        This test check that multiple Writer Framework applications embedded
        in FastAPI start completely and answer websocket request.
        """
        asgi_app: fastapi.FastAPI = FastAPI(lifespan=writer.serve.lifespan)
        asgi_app.mount("/app1", writer.serve.get_asgi_app(test_multiapp_dir / 'app1', "run"))
        asgi_app.mount("/app2", writer.serve.get_asgi_app(test_multiapp_dir / 'app2', "run"))

        with fastapi.testclient.TestClient(asgi_app) as client:
            # test websocket connection on app1
            with client.websocket_connect("/app1/api/stream") as websocket:
                websocket.send_json({
                    "type": "streamInit",
                    "trackingId": 0,
                    "payload": {
                        "sessionId": "bad_session"
                    }
                })
                with pytest.raises(fastapi.WebSocketDisconnect):
                    websocket.receive_bytes()

            # test websocket connection on app2
            with client.websocket_connect("/app2/api/stream") as websocket:
                websocket.send_json({
                    "type": "streamInit",
                    "trackingId": 0,
                    "payload": {
                        "sessionId": "bad_session"
                    }
                })
                with pytest.raises(fastapi.WebSocketDisconnect):
                    websocket.receive_bytes()

    def test_server_setup_hook_is_executed_when_its_present_and_enabled(self):
        """
        This test verifies that the server_setup.py hook is executed when the application
        is started with the enable_server_setup=True option.

        """
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(test_app_dir, "run", enable_server_setup=True)
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.get("/probes/healthcheck")
            assert res.status_code == 200
            assert res.text == '"1"'

    def test_server_setup_hook_is_ignored_when_its_disabled(self):
        """
        This test verifies that the server_setup.py hook is not executed
        when the application is started by disabling the server_setup.py hook.

        """
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(test_app_dir, "run", enable_server_setup=False)
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.get("/probes/healthcheck")
            assert res.status_code == 404

    def test_abstract_components(self):
        writer.abstract.register_abstract_template("sectiona", {
            "baseType": "section",
            "writer": {
                "name": "Section A"
            }
        })
        writer.abstract.register_abstract_template("columnb", {
            "baseType": "column",
            "writer": {
                "description": "Cloned Column component"
            }
        })

        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(
            test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.post("/api/init", json={
                "proposedSessionId": None
            }, headers={
                "Content-Type": "application/json"
            })
            abstract_templates = res.json().get("abstractTemplates")
            section_a = abstract_templates.get("sectiona")
            column_b = abstract_templates.get("columnb")
            assert section_a.get("writer").get("name") == "Section A"
            assert column_b.get("writer").get("description") == "Cloned Column component"
          
    def test_feature_flags(self):
        """
        This test verifies that feature flags are carried to the frontend.

        """
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(
            test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.post("/api/init", json={
                "proposedSessionId": None
            }, headers={
                "Content-Type": "application/json"
            })
            feature_flags = res.json().get("featureFlags")
            assert set(feature_flags) == {
                "blueprints",
                "flag_one",
                "flag_two",
                "api_trigger",
                "cron_trigger",
                "journal",
                "beforeDeprecationCutoffAbv2",
                "afterDeprecationCutoffAbv2",
            }

    def test_get_cron_triggers_api(self):
        """
        Test that the cron triggers API endpoint returns a list of cron trigger blocks.
        """
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.get("/private/api/cron-triggers")
            assert res.status_code == 200
            cron_triggers = res.json()
            assert isinstance(cron_triggers, list)

            for trigger in cron_triggers:
                assert "id" in trigger and trigger.get("id") is not None
                assert "blueprint_id" in trigger and trigger.get("blueprint_id") is not None
                assert "name" in trigger and trigger.get("name") is not None
                assert "cron_expression" in trigger and trigger.get("cron_expression") is not None
                assert "timezone" in trigger and trigger.get("timezone") is not None

    def test_create_blueprint_job_api(self, monkeypatch):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        monkeypatch.setenv("WRITER_SECRET_KEY", "abc")
        blueprint_id = "8ffkuce0ermsm9dr"

        with fastapi.testclient.TestClient(asgi_app) as client:
            with client.stream("POST", f"/private/api/blueprint/{blueprint_id}",
                                json={"proposedSessionId": None},
                                headers={"Content-Type": "application/json"}) as response:

                assert response.status_code == 200
                assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

                events = parse_sse_stream(response)

                # Verify we got at least one status event
                status_events = [e for e in events if e[0] == "status"]
                assert len(status_events) > 0

                # Verify terminal event exists
                terminal_events = [e for e in events if e[0] in ["artifact", "error"]]
                assert len(terminal_events) == 1

                event_type, final_payload = terminal_events[0]

                if event_type == "artifact":
                    assert "artifact" in final_payload
                    assert final_payload.get("artifact") == "987127"

    def test_create_blueprint_job_api_error_handling(self, monkeypatch):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        monkeypatch.setenv("WRITER_SECRET_KEY", "abc")

        with fastapi.testclient.TestClient(asgi_app) as client:
            with client.stream(
                "POST", "/private/api/blueprint/nonexistent",
                json={"proposedSessionId": None},
                headers={"Content-Type": "application/json"}
            ) as response:

                assert response.status_code == 200

                events = parse_sse_stream(response)
                assert len(events) > 0

                event_type, final_payload = events[-1]
                assert event_type == "error"
                assert "msg" in final_payload
                assert "not found" in final_payload["msg"].lower()

    def test_create_blueprint_job_api_streaming_events(self, monkeypatch):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        monkeypatch.setenv("WRITER_SECRET_KEY", "abc")
        blueprint_id = "8ffkuce0ermsm9dr"

        with fastapi.testclient.TestClient(asgi_app) as client:
            with client.stream(
                "POST", f"/private/api/blueprint/{blueprint_id}",
                json={"proposedSessionId": None},
                headers={"Content-Type": "application/json"}
            ) as response:

                events = parse_sse_stream(response)

                assert len(events) >= 2

                # First event should be "in progress" under "status"
                first_event_type, first_payload = events[0]
                assert first_event_type == "status"
                assert first_payload.get("status") == "in progress"
                assert "created_at" in first_payload

                # Last event should be either artifact or error
                event_type, final_payload = events[-1]
                assert event_type in ["artifact", "error"]

                if event_type == "artifact":
                    assert "artifact" in final_payload
                    assert "finished_at" in final_payload

                if event_type == "error":
                    assert "msg" in final_payload
                    assert "finished_at" in final_payload

    def test_health_endpoint_returns_ok_when_all_processes_running_run_mode(self):
        """
        Test that health endpoint returns {"status": "ok"} when all processes are running in run mode.
        Run mode has 2 processes: main web server and user app process.
        """
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.get("/api/health")
            assert res.status_code == 200
            assert res.json() == {"status": "ok"}

    def test_health_endpoint_returns_ok_when_all_processes_running_edit_mode(self):
        """
        Test that health endpoint returns {"status": "ok"} when all processes are running in edit mode.
        Edit mode has 3 processes: main web server, user app process, and project saver process.
        """
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.get("/api/health")
            assert res.status_code == 200
            assert res.json() == {"status": "ok"}

    def test_health_endpoint_returns_error_when_user_app_process_down(self):
        """
        Test that health endpoint returns 503 when user app process is not running.
        """
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            # Kill the user app process
            app_runner = asgi_app.state.app_runner
            if app_runner.app_process is not None:
                app_runner.app_process.terminate()
                app_runner.app_process.join(timeout=2)
            
            res = client.get("/api/health")
            assert res.status_code == 503
            response_json = res.json()
            assert response_json["status"] == "error"
            assert "User app process is not running" in response_json["message"]

    def test_health_endpoint_returns_error_when_project_saver_process_down_edit_mode(self):
        """
        Test that health endpoint returns 503 when project saver process is not running in edit mode.
        """
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            # Kill the project saver process
            app_runner = asgi_app.state.app_runner
            if app_runner.wf_project_context.write_files_async_process is not None:
                app_runner.wf_project_context.write_files_async_process.terminate()
                app_runner.wf_project_context.write_files_async_process.join(timeout=2)
            
            res = client.get("/api/health")
            assert res.status_code == 503
            response_json = res.json()
            assert response_json["status"] == "error"
            assert "Project saver process is not running" in response_json["message"]


class TestAutogen:

    LOCAL_ORIGIN = "http://localhost:4005"

    @pytest.fixture
    def fake_generate(self, monkeypatch):
        import sys
        import threading
        import types

        calls = []

        def generate_blueprint(description, token_header=None):
            calls.append({
                "description": description,
                "token_header": token_header,
                "thread": threading.current_thread(),
            })
            return {"blueprint": {"components": []}, "messages": []}

        fake_module = types.ModuleType("writer.autogen")
        fake_module.generate_blueprint = generate_blueprint  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "writer.autogen", fake_module)
        monkeypatch.setattr(writer, "autogen", fake_module, raising=False)
        return fake_module, calls

    def _init_session(self, client) -> str:
        res = client.post(
            "/api/init",
            json={"proposedSessionId": None},
            headers={"Content-Type": "application/json", "Origin": self.LOCAL_ORIGIN},
        )
        assert res.status_code == 200
        return res.json()["sessionId"]

    def _autogen(self, client, session_id, description="Build a chatbot", **headers):
        return client.post(
            "/api/autogen",
            json={"description": description},
            headers={
                "Origin": self.LOCAL_ORIGIN,
                "X-Session-Id": session_id,
                **headers,
            },
        )

    def test_rejected_in_run_mode(self, fake_generate):
        _, calls = fake_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            session_id = self._init_session(client)
            res = self._autogen(client, session_id)
            assert res.status_code == 403
        assert calls == []

    def test_rejected_without_session(self, fake_generate):
        _, calls = fake_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.post(
                "/api/autogen",
                json={"description": "Build a chatbot"},
                headers={"Origin": self.LOCAL_ORIGIN},
            )
            assert res.status_code == 403
            res = self._autogen(client, "not-a-real-session")
            assert res.status_code == 403
        assert calls == []

    def test_rejected_from_remote_origin(self, fake_generate):
        _, calls = fake_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            session_id = self._init_session(client)
            res = self._autogen(client, session_id, Origin="https://evil.example")
            assert res.status_code == 403
        assert calls == []

    def test_rejected_without_json_content_type(self, fake_generate):
        _, calls = fake_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            session_id = self._init_session(client)
            res = client.post(
                "/api/autogen",
                content=json.dumps({"description": "Build a chatbot"}).encode(),
                headers={"Origin": self.LOCAL_ORIGIN, "X-Session-Id": session_id},
            )
            assert "content-type" not in {k.lower() for k in res.request.headers}
            assert res.status_code == 415
        assert calls == []

    def test_rejects_oversized_description(self, fake_generate):
        from writer.ss_types import AUTOGEN_MAX_DESCRIPTION_LENGTH

        _, calls = fake_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            session_id = self._init_session(client)
            res = self._autogen(client, session_id, description="a" * (AUTOGEN_MAX_DESCRIPTION_LENGTH + 1))
            assert res.status_code == 422
        assert calls == []

    def test_generates_off_the_event_loop(self, fake_generate):
        import threading

        _, calls = fake_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            session_id = self._init_session(client)
            res = self._autogen(client, session_id, **{"X-Agent-Token": "agent-token"})
            assert res.status_code == 200
            assert res.json() == {"blueprint": {"components": []}, "messages": []}
        assert len(calls) == 1
        assert calls[0]["description"] == "Build a chatbot"
        assert calls[0]["token_header"] == "agent-token"
        assert calls[0]["thread"] is not threading.main_thread()

    def test_rate_limited_per_session(self, fake_generate, monkeypatch):
        monkeypatch.setattr(writer.serve, "AUTOGEN_RATE_LIMIT_MAX_REQUESTS", 2)
        _, calls = fake_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            session_id = self._init_session(client)
            assert self._autogen(client, session_id).status_code == 200
            assert self._autogen(client, session_id).status_code == 200
            assert self._autogen(client, session_id).status_code == 429
            other_session_id = self._init_session(client)
            assert self._autogen(client, other_session_id).status_code == 200
        assert len(calls) == 3

    def test_concurrent_request_rejected_while_server_stays_responsive(self, fake_generate):
        import threading

        fake_module, _ = fake_generate
        started = threading.Event()
        release = threading.Event()

        def slow_generate(description, token_header=None):
            started.set()
            assert release.wait(timeout=10)
            return {"blueprint": {"components": []}, "messages": []}

        fake_module.generate_blueprint = slow_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            session_id = self._init_session(client)
            results = {}
            worker = threading.Thread(
                target=lambda: results.setdefault("first", self._autogen(client, session_id))
            )
            worker.start()
            try:
                assert started.wait(timeout=10)
                assert client.get("/api/health").status_code == 200
                assert self._autogen(client, session_id).status_code == 429
            finally:
                release.set()
                worker.join(timeout=10)
            assert results["first"].status_code == 200

    def test_slot_held_until_cancelled_generation_finishes(self, fake_generate):
        import asyncio
        import contextlib
        import threading

        import httpx

        fake_module, calls = fake_generate
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_generate(description, token_header=None):
            calls.append(description)
            started.set()
            assert release.wait(timeout=10)
            finished.set()
            return {"blueprint": {"components": []}, "messages": []}

        fake_module.generate_blueprint = slow_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            session_id = self._init_session(client)
            headers = {"Origin": self.LOCAL_ORIGIN, "X-Session-Id": session_id}
            body = {"description": "Build a chatbot"}

            async def scenario():
                transport = httpx.ASGITransport(app=asgi_app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                    first = asyncio.create_task(ac.post("/api/autogen", json=body, headers=headers))
                    while not started.is_set():
                        await asyncio.sleep(0.01)
                    first.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await first
                    while_running = (await ac.post("/api/autogen", json=body, headers=headers)).status_code
                    release.set()
                    while not finished.is_set():
                        await asyncio.sleep(0.01)
                    for _ in range(100):
                        res = await ac.post("/api/autogen", json=body, headers=headers)
                        if res.status_code != 429:
                            break
                        await asyncio.sleep(0.01)
                    return while_running, res.status_code

            try:
                while_running, after = client.portal.call(scenario)
            finally:
                release.set()
            assert while_running == 429
            assert after == 200
        assert len(calls) == 2

    def test_idle_session_histories_are_pruned(self, fake_generate, monkeypatch):
        _, calls = fake_generate
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            route = next(r for r in asgi_app.routes if getattr(r, "path", None) == "/api/autogen")
            reserve = _closure_var(route.endpoint, "_reserve_autogen_slot")
            history = _closure_var(reserve, "autogen_history")

            first_session_id = self._init_session(client)
            assert self._autogen(client, first_session_id).status_code == 200
            assert first_session_id in history

            monkeypatch.setattr(writer.serve, "AUTOGEN_RATE_LIMIT_WINDOW_SECONDS", 0)
            second_session_id = self._init_session(client)
            assert self._autogen(client, second_session_id).status_code == 200
            assert first_session_id not in history
        assert len(calls) == 2


def _closure_var(func, name):
    return func.__closure__[func.__code__.co_freevars.index(name)].cell_contents

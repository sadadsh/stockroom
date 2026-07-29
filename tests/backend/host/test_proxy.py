from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from stockroom.api.serve import pick_free_port
from stockroom.host.proxy import SwitchableBackendProxy
from stockroom.host.run import _serve_in_thread


def _app(version: str) -> FastAPI:
    app = FastAPI()

    @app.get("/version")
    def get_version():
        return {"version": version}

    @app.post("/echo")
    async def echo(request: Request):
        return {"version": version, "body": (await request.body()).decode("utf-8")}

    @app.get("/request-origin")
    async def request_origin(request: Request):
        return {
            "host": request.headers.get("host"),
            "forwarded_host": request.headers.get("x-forwarded-host"),
            "forwarded_proto": request.headers.get("x-forwarded-proto"),
            "url": str(request.url),
        }

    return app


def _redirect_app(version: str, worker_base_url: str) -> FastAPI:
    app = _app(version)

    @app.get("/worker-redirect")
    def worker_redirect():
        return Response(
            status_code=307,
            headers={
                "Location": (f"{worker_base_url}/landing?source=private-worker#component-library")
            },
        )

    @app.get("/localhost-worker-redirect")
    def localhost_worker_redirect():
        port = worker_base_url.rsplit(":", 1)[1]
        return Response(
            status_code=302,
            headers={"Location": f"//localhost:{port}/landing?alias=localhost"},
        )

    @app.get("/external-redirect")
    def external_redirect():
        return Response(
            status_code=302,
            headers={"Location": "https://accounts.example.test/sign-in?next=%2Fsettings"},
        )

    @app.get("/landing")
    def landing():
        return {"version": version, "landed": True}

    return app


def test_stable_origin_switches_backend_and_streams_requests_without_reopening_client():
    local = _app("bundled")
    candidate = _app("candidate")
    port = pick_free_port()
    server, thread = _serve_in_thread(candidate, port)
    proxy = SwitchableBackendProxy(local)
    try:
        with TestClient(proxy, base_url="http://stable.stockroom") as client:
            assert client.get("/version").json() == {"version": "bundled"}

            proxy.switch(f"http://127.0.0.1:{port}")

            assert client.get("/version").json() == {"version": "candidate"}
            assert client.post("/echo", content="payload").json() == {
                "version": "candidate",
                "body": "payload",
            }

            proxy.switch(None)
            assert client.get("/version").json() == {"version": "bundled"}
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_worker_receives_the_webviews_stable_public_host_not_its_private_port():
    local = _app("bundled")
    port = pick_free_port()
    candidate = _app("candidate")
    server, thread = _serve_in_thread(candidate, port)
    proxy = SwitchableBackendProxy(local)
    proxy.switch(f"http://127.0.0.1:{port}")
    try:
        with TestClient(proxy, base_url="http://stable.stockroom:8123") as client:
            body = client.get("/request-origin").json()

        assert body == {
            "host": "stable.stockroom:8123",
            "forwarded_host": "stable.stockroom:8123",
            "forwarded_proto": "http",
            "url": "http://stable.stockroom:8123/request-origin",
        }
        assert str(port) not in body["host"]
        assert str(port) not in body["url"]
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_same_worker_absolute_redirect_is_rewritten_to_the_stable_public_origin():
    local = _app("bundled")
    port = pick_free_port()
    worker_base_url = f"http://127.0.0.1:{port}"
    candidate = _redirect_app("candidate", worker_base_url)
    server, thread = _serve_in_thread(candidate, port)
    proxy = SwitchableBackendProxy(local)
    proxy.switch(worker_base_url)
    try:
        with TestClient(proxy, base_url="http://stable.stockroom") as client:
            first = client.get("/worker-redirect", follow_redirects=False)
            followed = client.get("/worker-redirect")

        assert first.status_code == 307
        assert first.headers["location"] == "/landing?source=private-worker#component-library"
        assert worker_base_url not in first.headers["location"]
        assert followed.json() == {"version": "candidate", "landed": True}
        assert str(followed.url).startswith("http://stable.stockroom/landing")
        assert "127.0.0.1" not in str(followed.url)
        assert str(port) not in str(followed.url)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_same_worker_localhost_network_redirect_is_also_made_origin_relative():
    local = _app("bundled")
    port = pick_free_port()
    worker_base_url = f"http://127.0.0.1:{port}"
    candidate = _redirect_app("candidate", worker_base_url)
    server, thread = _serve_in_thread(candidate, port)
    proxy = SwitchableBackendProxy(local)
    proxy.switch(worker_base_url)
    try:
        with TestClient(proxy, base_url="http://stable.stockroom") as client:
            response = client.get("/localhost-worker-redirect", follow_redirects=False)

        assert response.headers["location"] == "/landing?alias=localhost"
        assert "//localhost:" not in response.headers["location"]
        assert str(port) not in response.headers["location"]
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_external_redirect_is_preserved_verbatim():
    local = _app("bundled")
    port = pick_free_port()
    worker_base_url = f"http://127.0.0.1:{port}"
    candidate = _redirect_app("candidate", worker_base_url)
    server, thread = _serve_in_thread(candidate, port)
    proxy = SwitchableBackendProxy(local)
    proxy.switch(worker_base_url)
    try:
        with TestClient(proxy, base_url="http://stable.stockroom") as client:
            response = client.get("/external-redirect", follow_redirects=False)

        assert (
            response.headers["location"] == "https://accounts.example.test/sign-in?next=%2Fsettings"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_proxy_refuses_any_non_loopback_target():
    proxy = SwitchableBackendProxy(_app("bundled"))

    try:
        proxy.switch("https://example.com")
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback backend target was accepted")

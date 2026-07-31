from eagle.main import check_url


class FakeResponse:
    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.content = body.encode("utf-8")
        self.encoding = "utf-8"
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_transient_server_error_is_recheck(monkeypatch) -> None:
    response = FakeResponse(503)
    monkeypatch.setattr("eagle.main.requests.get", lambda *args, **kwargs: response)

    assert check_url("https://example.com/job/1") is None
    assert response.closed is True


def test_explicit_not_found_is_closed(monkeypatch) -> None:
    response = FakeResponse(404)
    monkeypatch.setattr("eagle.main.requests.get", lambda *args, **kwargs: response)

    assert check_url("https://example.com/job/2") is False


def test_live_page_and_closed_marker_are_distinguished(monkeypatch) -> None:
    live = FakeResponse(200, "Apply now for this role")
    monkeypatch.setattr("eagle.main.requests.get", lambda *args, **kwargs: live)
    assert check_url("https://example.com/job/live") is True

    closed = FakeResponse(200, "This position has been filled")
    monkeypatch.setattr("eagle.main.requests.get", lambda *args, **kwargs: closed)
    assert check_url("https://example.com/job/closed") is False

from fastapi.testclient import TestClient

from app.main import app


def test_streaming_generate():

    with TestClient(app) as client:

        with client.stream(
            "POST",
            "/generate",
            json={
                "prompt": "hello world",
                "max_new_tokens": 5,
            },
        ) as response:

            assert response.status_code == 200

            tokens = list(response.iter_lines())

    assert len(tokens) == 5

    assert "tok1" in tokens[0]
    assert "tok5" in tokens[-1]
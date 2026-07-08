import pytest
from app.models import GenerationRequest, END_OF_STREAM


@pytest.mark.asyncio
async def test_token_stream_order():
    req = GenerationRequest(
        request_id="r1",
        prompt="hello",
        max_new_tokens=2,
    )

    await req.token_stream.put("tok1")
    await req.token_stream.put("tok2")
    await req.token_stream.put(END_OF_STREAM)

    assert await req.token_stream.get() == "tok1"
    assert await req.token_stream.get() == "tok2"
    assert await req.token_stream.get() is END_OF_STREAM
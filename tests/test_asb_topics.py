from open_vi.asb.topics import (
    message_type_from_dest,
    subscribe_aliases,
    topic_dest,
)


def test_message_type_from_dest() -> None:
    assert (
        message_type_from_dest("/topic/MA_FlightCommand") == "MA_FlightCommand"
    )
    assert (
        message_type_from_dest("/topic/MA_FlightCommand<None>")
        == "MA_FlightCommand"
    )
    assert message_type_from_dest("MA_FlightCommand") == "MA_FlightCommand"


def test_subscribe_aliases() -> None:
    assert subscribe_aliases("MA_Fault") == [
        "/topic/MA_Fault",
        "/topic/MA_Fault<None>",
    ]
    assert topic_dest("MA_Fault") == "/topic/MA_Fault"

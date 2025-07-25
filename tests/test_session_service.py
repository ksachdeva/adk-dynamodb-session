from datetime import datetime, timezone
from typing import Generator

import pytest
from google.adk.events import Event, EventActions
from google.adk.sessions.base_session_service import GetSessionConfig
from google.genai import types

from adk_dynamodb_session import DynamoDBSessionService


@pytest.fixture(scope="function", autouse=True)
def session_service() -> Generator[DynamoDBSessionService, None, None]:
    db_service = DynamoDBSessionService()
    db_service.create_table_if_not_exists()
    yield db_service
    db_service.delete_table()


@pytest.mark.asyncio
async def test_get_empty_session(session_service: DynamoDBSessionService) -> None:
    session_1 = await session_service.create_session(app_name="test_app", user_id="test_user")
    assert session_1 is not None

    assert session_1.app_name == "test_app"
    assert session_1.user_id == "test_user"
    assert session_1.id is not None


@pytest.mark.asyncio
async def test_create_get_session(session_service: DynamoDBSessionService) -> None:
    app_name = "my_app"
    user_id = "test_user"
    state = {"key": "value"}

    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        state=state,
    )
    assert session is not None
    assert session.app_name == app_name
    assert session.user_id == user_id
    assert session.id
    assert session.state == state

    assert session.last_update_time <= datetime.now().astimezone(timezone.utc).timestamp()

    got_session = await session_service.get_session(app_name=app_name, user_id=user_id, session_id=session.id)
    assert got_session is not None
    assert got_session == session
    assert got_session.last_update_time <= datetime.now().astimezone(timezone.utc).timestamp()

    session_id = session.id
    await session_service.delete_session(app_name=app_name, user_id=user_id, session_id=session_id)

    assert await session_service.get_session(app_name=app_name, user_id=user_id, session_id=session.id) != session


@pytest.mark.asyncio
async def test_create_and_list_sessions(session_service: DynamoDBSessionService) -> None:
    app_name = "my_app"
    user_id = "test_user"

    session_ids = ["session" + str(i) for i in range(5)]
    for session_id in session_ids:
        await session_service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)

    list_sessions_response = await session_service.list_sessions(app_name=app_name, user_id=user_id)
    sessions = list_sessions_response.sessions
    assert len(sessions) == len(session_ids)
    for i in range(len(sessions)):
        assert sessions[i].id == session_ids[i]


@pytest.mark.asyncio
async def test_append_event_bytes(session_service: DynamoDBSessionService) -> None:
    app_name = "my_app"
    user_id = "user"

    session = await session_service.create_session(app_name=app_name, user_id=user_id)

    test_content = types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(data=b"test_image_data", mime_type="image/png"),
        ],
    )
    test_grounding_metadata = types.GroundingMetadata(
        search_entry_point=types.SearchEntryPoint(sdk_blob=b"test_sdk_blob")
    )
    event = Event(
        invocation_id="invocation",
        author="user",
        content=test_content,
        grounding_metadata=test_grounding_metadata,
    )
    await session_service.append_event(session=session, event=event)

    assert session.events[0].content == test_content

    session = await session_service.get_session(app_name=app_name, user_id=user_id, session_id=session.id)
    assert session is not None
    events = session.events
    assert len(events) == 1
    assert events[0].content == test_content
    assert events[0].grounding_metadata == test_grounding_metadata


@pytest.mark.asyncio
async def test_append_event_complete(session_service: DynamoDBSessionService) -> None:
    app_name = "my_app"
    user_id = "user"

    session = await session_service.create_session(app_name=app_name, user_id=user_id)
    event = Event(
        invocation_id="invocation",
        author="user",
        content=types.Content(role="user", parts=[types.Part(text="test_text")]),
        turn_complete=True,
        partial=False,
        actions=EventActions(
            artifact_delta={
                "file": 0,
            },
            transfer_to_agent="agent",
            escalate=True,
        ),
        long_running_tool_ids={"tool1"},
        error_code="error_code",
        error_message="error_message",
        interrupted=True,
    )
    await session_service.append_event(session=session, event=event)

    got_session = await session_service.get_session(app_name=app_name, user_id=user_id, session_id=session.id)
    assert got_session == session


@pytest.mark.asyncio
async def test_get_session_with_config(session_service: DynamoDBSessionService) -> None:
    app_name = "my_app"
    user_id = "user"

    num_test_events = 5
    session = await session_service.create_session(app_name=app_name, user_id=user_id)
    for i in range(1, num_test_events + 1):
        event = Event(author="user", timestamp=i)
        await session_service.append_event(session, event)

    # No config, expect all events to be returned.
    session = await session_service.get_session(app_name=app_name, user_id=user_id, session_id=session.id)
    assert session is not None
    events = session.events
    assert len(events) == num_test_events

    # Only expect the most recent 3 events.
    num_recent_events = 3
    config = GetSessionConfig(num_recent_events=num_recent_events)
    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id, config=config
    )
    assert session is not None
    events = session.events
    assert len(events) == num_recent_events
    assert events[0].timestamp == num_test_events - num_recent_events + 1

    # Only expect events after timestamp 4.0 (inclusive), i.e., 2 events.
    after_timestamp = 4.0
    config = GetSessionConfig(after_timestamp=after_timestamp)
    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id, config=config
    )
    assert session is not None
    events = session.events
    assert len(events) == num_test_events - after_timestamp + 1
    assert events[0].timestamp == after_timestamp

    # Expect no events if none are > after_timestamp.
    way_after_timestamp = num_test_events * 10
    config = GetSessionConfig(after_timestamp=way_after_timestamp)
    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id, config=config
    )
    assert session is not None
    assert not session.events

    # Both filters applied, i.e., of 3 most recent events, only 2 are after
    # timestamp 4.0, so expect 2 events.
    config = GetSessionConfig(after_timestamp=after_timestamp, num_recent_events=num_recent_events)
    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id, config=config
    )
    assert session is not None
    events = session.events
    assert len(events) == num_test_events - after_timestamp + 1


@pytest.mark.asyncio
async def test_session_state(session_service: DynamoDBSessionService) -> None:
    app_name = "my_app"
    user_id_1 = "user1"
    user_id_2 = "user2"
    user_id_malicious = "malicious"
    session_id_11 = "session11"
    session_id_12 = "session12"
    session_id_2 = "session2"
    state_11 = {"key11": "value11"}
    state_12 = {"key12": "value12"}

    session_11 = await session_service.create_session(
        app_name=app_name,
        user_id=user_id_1,
        state=state_11,
        session_id=session_id_11,
    )
    await session_service.create_session(
        app_name=app_name,
        user_id=user_id_1,
        state=state_12,
        session_id=session_id_12,
    )
    await session_service.create_session(app_name=app_name, user_id=user_id_2, session_id=session_id_2)

    await session_service.create_session(app_name=app_name, user_id=user_id_malicious, session_id=session_id_11)

    assert session_11.state.get("key11") == "value11"

    event = Event(
        invocation_id="invocation",
        author="user",
        content=types.Content(role="user", parts=[types.Part(text="text")]),
        actions=EventActions(
            state_delta={
                "app:key": "value",
                "user:key1": "value1",
                "temp:key": "temp",
                "key11": "value11_new",
            }
        ),
    )
    await session_service.append_event(session=session_11, event=event)

    # User and app state is stored, temp state is filtered.
    assert session_11.state.get("app:key") == "value"
    assert session_11.state.get("key11") == "value11_new"
    assert session_11.state.get("user:key1") == "value1"
    assert not session_11.state.get("temp:key")

    session_12 = await session_service.get_session(app_name=app_name, user_id=user_id_1, session_id=session_id_12)
    assert session_12 is not None
    # After getting a new instance, the session_12 got the user and app state,
    # even append_event is not applied to it, temp state has no effect
    assert session_12.state.get("key12") == "value12"
    assert not session_12.state.get("temp:key")

    # The user1's state is not visible to user2, app state is visible
    session_2 = await session_service.get_session(app_name=app_name, user_id=user_id_2, session_id=session_id_2)
    assert session_2 is not None
    assert session_2.state.get("app:key") == "value"
    assert not session_2.state.get("user:key1")

    assert not session_2.state.get("user:key1")

    # The change to session_11 is persisted
    session_11 = await session_service.get_session(app_name=app_name, user_id=user_id_1, session_id=session_id_11)
    assert session_11 is not None
    assert session_11.state.get("key11") == "value11_new"
    assert session_11.state.get("user:key1") == "value1"
    assert not session_11.state.get("temp:key")

    # Make sure a malicious user can obtain a session and events not belonging to them
    session_mismatch = await session_service.get_session(
        app_name=app_name, user_id=user_id_malicious, session_id=session_id_11
    )
    assert session_mismatch is not None

    assert len(session_mismatch.events) == 0


@pytest.mark.asyncio
async def test_create_new_session_will_merge_states(session_service: DynamoDBSessionService) -> None:
    app_name = "my_app"
    user_id = "user"
    session_id_1 = "session1"
    session_id_2 = "session2"
    state_1 = {"key1": "value1"}

    session_1 = await session_service.create_session(
        app_name=app_name, user_id=user_id, state=state_1, session_id=session_id_1
    )

    event = Event(
        invocation_id="invocation",
        author="user",
        content=types.Content(role="user", parts=[types.Part(text="text")]),
        actions=EventActions(
            state_delta={
                "app:key": "value",
                "user:key1": "value1",
                "temp:key": "temp",
            }
        ),
    )
    await session_service.append_event(session=session_1, event=event)

    # User and app state is stored, temp state is filtered.
    assert session_1.state.get("app:key") == "value"
    assert session_1.state.get("key1") == "value1"
    assert session_1.state.get("user:key1") == "value1"
    assert not session_1.state.get("temp:key")

    session_2 = await session_service.create_session(
        app_name=app_name, user_id=user_id, state={}, session_id=session_id_2
    )
    # Session 2 has the persisted states
    assert session_2.state.get("app:key") == "value"
    assert session_2.state.get("user:key1") == "value1"
    assert not session_2.state.get("key1")
    assert not session_2.state.get("temp:key")

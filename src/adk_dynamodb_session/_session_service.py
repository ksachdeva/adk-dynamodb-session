from __future__ import annotations

import copy
import datetime
import json
import logging
import uuid
from typing import Any, Optional

from google.adk.events.event import Event
from google.adk.sessions.base_session_service import BaseSessionService, GetSessionConfig, ListSessionsResponse
from google.adk.sessions.session import Session
from google.adk.sessions.state import State
from google.genai import types
from pynamodb.exceptions import DoesNotExist
from typing_extensions import override

from ._models import ADKEntityModel, AppStateModel, EventModel, SessionModel, UserStateModel

logger = logging.getLogger("adk_dynamodb_service." + __name__)


def _decode_content(
    content: Optional[dict[str, Any]],
) -> Optional[types.Content]:
    """Decodes a content object from a JSON dictionary."""
    if not content:
        return None
    return types.Content.model_validate(content)


def _decode_grounding_metadata(
    grounding_metadata: Optional[dict[str, Any]],
) -> Optional[types.GroundingMetadata]:
    """Decodes a grounding metadata object from a JSON dictionary."""
    if not grounding_metadata:
        return None
    return types.GroundingMetadata.model_validate(grounding_metadata)


def _extract_state_delta(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    app_state_delta = {}
    user_state_delta = {}
    session_state_delta = {}
    if state:
        for key in state.keys():
            if key.startswith(State.APP_PREFIX):
                app_state_delta[key.removeprefix(State.APP_PREFIX)] = state[key]
            elif key.startswith(State.USER_PREFIX):
                user_state_delta[key.removeprefix(State.USER_PREFIX)] = state[key]
            elif not key.startswith(State.TEMP_PREFIX):
                session_state_delta[key] = state[key]
    return app_state_delta, user_state_delta, session_state_delta


def _merge_state(
    app_state: dict[str, Any],
    user_state: dict[str, Any],
    session_state: dict[str, Any],
) -> dict[str, Any]:
    # Merge states for response
    merged_state = copy.deepcopy(session_state)
    for key in app_state.keys():
        merged_state[State.APP_PREFIX + key] = app_state[key]
    for key in user_state.keys():
        merged_state[State.USER_PREFIX + key] = user_state[key]
    return merged_state


def _make_session_hash_key(
    app_name: str,
    user_id: str,
) -> str:
    """
    Create a hash key for the session in DynamoDB.
    The format is: SESSION#<app_name>#<user_id>
    """
    return f"SESSION#{app_name}#{user_id}"


def _make_session_range_key(
    session_id: str,
) -> str:
    """
    Create a range key for the session in DynamoDB.
    The format is: #METADATA#<session_id>
    """
    return f"#METADATA#{session_id}"


def _make_app_state_hash_key(app_name: str) -> str:
    """
    Create a hash key for the app state in DynamoDB.
    The format is: AppState#<app_name>
    """
    return f"AppState#{app_name}"


def _make_app_state_range_key(app_name: str) -> str:
    """
    Create a range key for the app state in DynamoDB.
    The format is: #METADATA#<app_name>
    """
    return f"#METADATA#{app_name}"


def _make_user_state_hash_key(app_name: str, user_id: str) -> str:
    """
    Create a hash key for the user state in DynamoDB.
    The format is: UserState#<app_name>#<user_id>
    """
    return f"UserState#{app_name}#{user_id}"


def _make_user_state_range_key(user_id: str) -> str:
    """
    Create a range key for the user state in DynamoDB.
    The format is: #METADATA#<user_id>
    """
    return f"#METADATA#{user_id}"


def _make_event_hash_key(
    session_id: str,
    app_name: str,
    user_id: str,
) -> str:
    """
    Create a hash key for the event in DynamoDB.
    The format is: Event#<app_name>#<user_id>#<session_id>
    """
    return f"Event#{app_name}#{user_id}#{session_id}"


def _make_event_range_key(
    session_id: str,
    event: Event,
) -> str:
    """
    Create a range key for the event in DynamoDB.
    The format is: #METADATA#<session_id>
    """
    return f"#METADATA#{session_id}#{event.timestamp}"


def _create_or_update_app_state(
    app_name: str,
    app_state_delta: dict[str, Any],
    current_time: datetime.datetime,
) -> dict[str, Any]:
    updated_app_state: dict[str, Any] = {}

    try:
        app_state_model = AppStateModel.get(
            hash_key=_make_app_state_hash_key(app_name),
            range_key=_make_app_state_range_key(app_name),
        )
        app_state_str = app_state_model.app_state or "{}"
        updated_app_state = json.loads(app_state_str)
        updated_app_state.update(app_state_delta)
        app_state_model.update(
            actions=[
                AppStateModel.app_state.set(json.dumps(updated_app_state)),
                AppStateModel.app_state_update_time.set(current_time.isoformat()),
            ]
        )
    except DoesNotExist:
        updated_app_state = app_state_delta
        app_state_model = AppStateModel(
            hash_key=_make_app_state_hash_key(app_name),
            range_key=_make_app_state_range_key(app_name),
            app_state=json.dumps(updated_app_state),
            app_state_update_time=current_time.isoformat(),
        )
        app_state_model.save()

    return updated_app_state


def _get_user_state(
    app_name: str,
    user_id: str,
) -> dict[str, Any]:
    """
    Fetches the user state from DynamoDB.
    Returns None if the user state does not exist.
    """
    try:
        user_state_model = UserStateModel.get(
            hash_key=_make_user_state_hash_key(app_name, user_id),
            range_key=_make_user_state_range_key(user_id),
        )
        return json.loads(user_state_model.user_state)
    except DoesNotExist:
        return {}


def _get_app_state(
    app_name: str,
) -> dict[str, Any]:
    """
    Fetches the app state from DynamoDB.
    Returns None if the app state does not exist.
    """
    try:
        app_state_model = AppStateModel.get(
            hash_key=_make_app_state_hash_key(app_name),
            range_key=_make_app_state_range_key(app_name),
        )
        return json.loads(app_state_model.app_state)
    except DoesNotExist:
        return {}


def _create_or_update_user_state(
    app_name: str,
    user_id: str,
    user_state_delta: dict[str, Any],
    current_time: datetime.datetime,
) -> dict[str, Any]:
    updated_user_state: dict[str, Any] = {}

    try:
        user_state_model = UserStateModel.get(
            hash_key=_make_user_state_hash_key(app_name, user_id),
            range_key=_make_user_state_range_key(user_id),
        )
        user_state_str = user_state_model.user_state or "{}"
        updated_user_state = json.loads(user_state_str)
        updated_user_state.update(user_state_delta)
        user_state_model.update(
            actions=[
                UserStateModel.user_state.set(json.dumps(updated_user_state)),
                UserStateModel.user_state_update_time.set(current_time.isoformat()),
            ]
        )
    except DoesNotExist:
        updated_user_state = user_state_delta
        user_state_model = UserStateModel(
            hash_key=_make_user_state_hash_key(app_name, user_id),
            range_key=_make_user_state_range_key(user_id),
            user_state=json.dumps(updated_user_state),
            user_state_update_time=current_time.isoformat(),
        )
        user_state_model.save()

    return updated_user_state


class DynamoDBSessionService(BaseSessionService):
    """A session service that uses AWS DynamoDB for storage."""

    def create_table_if_not_exists(
        self,
        read_capacity_units: int | None = None,
        write_capacity_units: int | None = None,
        billing_mode: str | None = None,
        ignore_update_ttl_errors: bool = False,
    ) -> None:
        ADKEntityModel.create_table(
            read_capacity_units=read_capacity_units or 5,
            write_capacity_units=write_capacity_units or 5,
            billing_mode=billing_mode,
            ignore_update_ttl_errors=ignore_update_ttl_errors,
            wait=True,
        )

    def delete_table(self) -> None:
        ADKEntityModel.delete_table(wait=True)

    @override
    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        session_id = session_id.strip() if session_id and session_id.strip() else str(uuid.uuid4())

        # the supplied state may contain app, user, and session state.
        # we need to extract the deltas for each of them.
        app_state_delta, user_state_delta, session_state_delta = _extract_state_delta(state or {})

        current_time = datetime.datetime.now()

        # create or update the app state in DynamoDB
        updated_app_state = _create_or_update_app_state(app_name, app_state_delta, current_time)

        # create or update the user state in DynamoDB
        updated_user_state = _create_or_update_user_state(app_name, user_id, user_state_delta, current_time)

        session_model = SessionModel(
            hash_key=_make_session_hash_key(app_name, user_id),
            range_key=_make_session_range_key(session_id),
            session_id=session_id,
            session_state=json.dumps(session_state_delta),
            create_time=current_time.isoformat(),
            update_time=current_time.isoformat(),
        )

        session_model.save()

        # we need to return the updated state
        merged_state = _merge_state(updated_app_state, updated_user_state, session_state_delta)
        return Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=merged_state,
            events=[],
            last_update_time=current_time.timestamp(),
        )

    @override
    async def delete_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> None:
        session_model = SessionModel(
            hash_key=_make_session_hash_key(app_name, user_id),
            range_key=_make_session_range_key(session_id),
        )
        session_model.delete()

        # must also delete the events associated with this session
        event_models = EventModel.query(hash_key=_make_event_hash_key(session_id, app_name, user_id))
        for event_model in event_models:
            event_model.delete()

    @override
    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        try:
            session = SessionModel.get(
                hash_key=_make_session_hash_key(app_name, user_id),
                range_key=_make_session_range_key(session_id),
            )
        except DoesNotExist:
            logger.warning(f"Session {session_id} for app {app_name} and user {user_id} does not exist.")
            return None

        session_state = json.loads(session.session_state or "{}")
        update_time = datetime.datetime.fromisoformat(session.update_time)

        # now we need to get the App state and user state and merge them with the session state
        user_state = _get_user_state(app_name, user_id)
        app_state = _get_app_state(app_name)

        state = _merge_state(app_state, user_state, session_state)

        # fetch the events for this session
        event_models = EventModel.query(hash_key=_make_event_hash_key(session_id, app_name, user_id))
        events: list[Event] = []

        for e in event_models:
            event = Event(
                id=e.event_id,
                invocation_id=e.invocation_id,
                author=e.author,
                branch=e.branch,
                timestamp=e.timestamp,
                partial=e.partial,
                turn_complete=e.turn_complete,
                interrupted=e.interrupted,
                actions=e.actions,
                error_code=e.error_code,
                error_message=e.error_message,
                long_running_tool_ids=e.long_running_tool_ids,
            )
            if e.content:
                event.content = _decode_content(json.loads(e.content))
            if e.grounding_metadata:
                event.grounding_metadata = _decode_grounding_metadata(json.loads(e.grounding_metadata))

            events.append(event)

        # sort the events by timestamp
        events.sort(key=lambda e: e.timestamp)

        if config:
            # Apply the config filters
            if config.after_timestamp:
                events = [e for e in events if e.timestamp >= config.after_timestamp]
            if config.num_recent_events is not None:
                events = events[-config.num_recent_events :]

        return Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=state or {},
            events=events,
            last_update_time=update_time.timestamp(),
        )

    @override
    async def list_sessions(
        self,
        *,
        app_name: str,
        user_id: str,
    ) -> ListSessionsResponse:
        results = SessionModel.query(hash_key=f"SESSION#{app_name}#{user_id}")

        sessions: list[Session] = []
        for r in results:
            state = json.loads(r.session_state or "{}")
            update_time = datetime.datetime.fromisoformat(r.update_time)

            # in DatabaseSessionService, no events are fetched here,
            # so we create an empty list of events.
            sessions.append(
                Session(
                    id=r.session_id,
                    app_name=app_name,
                    user_id=user_id,
                    state=state or {},
                    events=[],
                    last_update_time=update_time.timestamp(),
                )
            )

        return ListSessionsResponse(sessions=sessions)

    @override
    async def append_event(self, session: Session, event: Event) -> Event:
        """Appends an event to a session object."""
        logger.info(f"Append event: {event} to session {session.id}")
        if event.partial:
            return event

        # 1. Check if timestamp is stale
        # 2. Update session attributes based on event config
        # 3. Store event to table

        session_model = SessionModel.get(
            hash_key=_make_session_hash_key(session.app_name, session.user_id),
            range_key=_make_session_range_key(session.id),
        )

        update_time = datetime.datetime.fromisoformat(session_model.update_time)

        if update_time.timestamp() > session.last_update_time:
            raise ValueError(
                "The last_update_time provided in the session object"
                f" {datetime.datetime.fromtimestamp(session.last_update_time):'%Y-%m-%d %H:%M:%S'} is"
                " earlier than the update_time in the storage_session"
                f" {update_time:'%Y-%m-%d %H:%M:%S'}. Please check"
                " if it is a stale session."
            )

        # App state
        app_state_model = AppStateModel.get(
            hash_key=_make_app_state_hash_key(session.app_name),
            range_key=_make_app_state_range_key(session.app_name),
        )

        # User state
        user_state_model = UserStateModel.get(
            hash_key=_make_user_state_hash_key(session.app_name, session.user_id),
            range_key=_make_user_state_range_key(session.user_id),
        )

        app_state = json.loads(app_state_model.app_state)
        user_state = json.loads(user_state_model.user_state)
        session_state = json.loads(session_model.session_state)

        # Extract state delta
        app_state_delta: dict[str, Any] = {}
        user_state_delta: dict[str, Any] = {}
        session_state_delta: dict[str, Any] = {}
        if event.actions:
            if event.actions.state_delta:
                app_state_delta, user_state_delta, session_state_delta = _extract_state_delta(event.actions.state_delta)

        current_time = datetime.datetime.now()

        # Merge state and update storage
        if app_state_delta:
            app_state.update(app_state_delta)
            app_state_model.update(
                actions=[
                    AppStateModel.app_state.set(json.dumps(app_state)),
                    AppStateModel.app_state_update_time.set(current_time.isoformat()),
                ]
            )
        if user_state_delta:
            user_state.update(user_state_delta)
            user_state_model.update(
                actions=[
                    UserStateModel.user_state.set(json.dumps(user_state)),
                    UserStateModel.user_state_update_time.set(current_time.isoformat()),
                ]
            )
        if session_state_delta:
            session_state.update(session_state_delta)
            session_model.update(
                actions=[
                    SessionModel.session_state.set(json.dumps(session_state)),
                    SessionModel.update_time.set(current_time.isoformat()),
                ]
            )

        event_model_attributes: dict[str, Any] = {
            "session_id": session.id,
            "event_id": event.id,
            "invocation_id": event.invocation_id,
            "author": event.author,
            "branch": event.branch,
            "timestamp": event.timestamp,
            "partial": event.partial,
            "turn_complete": event.turn_complete,
            "interrupted": event.interrupted,
            "actions": event.actions,
            "error_code": event.error_code,
            "error_message": event.error_message,
            "hash_key": _make_event_hash_key(session.id, session.app_name, session.user_id),
            "range_key": _make_event_range_key(session.id, event),
            "long_running_tool_ids": event.long_running_tool_ids,
        }

        if event.content:
            event_model_attributes.update(
                {
                    "content": event.content.model_dump_json(exclude_none=True),
                }
            )

        if event.grounding_metadata:
            event_model_attributes.update(
                {
                    "grounding_metadata": event.grounding_metadata.model_dump_json(exclude_none=True),
                }
            )

        event_model = EventModel(**event_model_attributes)

        event_model.save()

        # Also update the in-memory session
        await super().append_event(session=session, event=event)

        return event

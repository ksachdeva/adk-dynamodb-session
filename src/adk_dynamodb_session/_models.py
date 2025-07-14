import os
import pickle
from typing import Any

from google.adk.events import Event
from pynamodb.attributes import (
    Attribute,
    BooleanAttribute,
    DiscriminatorAttribute,
    NumberAttribute,
    UnicodeAttribute,
    UnicodeSetAttribute,
)
from pynamodb.constants import BINARY
from pynamodb.models import Model


class PickleAttribute(Attribute[object]):
    """
    This class will serializer/deserialize any picklable Python object.
    The value will be stored as a binary attribute in DynamoDB.
    """

    attr_type = BINARY

    def serialize(self, value: Any) -> bytes:
        return pickle.dumps(value)

    def deserialize(self, value: Any) -> Any:
        return pickle.loads(value)


class ADKEntityModel(Model):
    """
    A PynamoDB model representing a session in DynamoDB.
    """

    # This is not the right way but all the investigation in pynamoDB
    # shows that this is the only way to set the table name dynamically.
    # https://github.com/pynamodb/PynamoDB/issues/177
    class Meta:
        table_name = os.environ.get("ADK_DYNAMODB_SESSION_TABLE_NAME", "adk_session")

    PK = UnicodeAttribute(hash_key=True)
    SK = UnicodeAttribute(range_key=True)

    Type = DiscriminatorAttribute(attr_name="Type")


class SessionModel(ADKEntityModel, discriminator="Session"):
    session_id = UnicodeAttribute()
    session_state = UnicodeAttribute()
    create_time = UnicodeAttribute()
    update_time = UnicodeAttribute()

    @staticmethod
    def make_session_hash_key(
        app_name: str,
        user_id: str,
    ) -> str:
        """
        Create a hash key for the session in DynamoDB.
        The format is: SESSION#<app_name>#<user_id>
        """
        return f"SESSION#{app_name}#{user_id}"

    @staticmethod
    def make_session_range_key(
        session_id: str,
    ) -> str:
        """
        Create a range key for the session in DynamoDB.
        The format is: #METADATA#<session_id>
        """
        return f"#METADATA#{session_id}"


class EventModel(ADKEntityModel, discriminator="Event"):
    event_id = UnicodeAttribute()
    session_id = UnicodeAttribute()
    invocation_id = UnicodeAttribute()
    author = UnicodeAttribute()
    branch = UnicodeAttribute(null=True)  # Optional branch for events
    timestamp = NumberAttribute()
    partial = BooleanAttribute(default=False, null=True)  # Indicates if the event is a partial update
    content = UnicodeAttribute(null=True)  # For flexible event content
    grounding_metadata = UnicodeAttribute(null=True)
    interrupted = BooleanAttribute(default=False, null=True)  # Indicates if the event was interrupted
    turn_complete = BooleanAttribute(default=False, null=True)  # Indicates if the turn is complete
    error_code = UnicodeAttribute(null=True)  # Optional error code for events
    error_message = UnicodeAttribute(null=True)  # Optional error message for events
    long_running_tool_ids = UnicodeSetAttribute(null=True)
    actions = PickleAttribute(null=True)  # For flexible event actions

    @staticmethod
    def make_event_hash_key(
        session_id: str,
        app_name: str,
        user_id: str,
    ) -> str:
        """
        Create a hash key for the event in DynamoDB.
        The format is: Event#<app_name>#<user_id>#<session_id>
        """
        return f"Event#{app_name}#{user_id}#{session_id}"

    @staticmethod
    def make_event_range_key(
        session_id: str,
        event: Event,
    ) -> str:
        """
        Create a range key for the event in DynamoDB.
        The format is: #METADATA#<session_id>
        """
        return f"#METADATA#{session_id}#{event.timestamp}"


class AppStateModel(ADKEntityModel, discriminator="AppState"):
    app_state = UnicodeAttribute()
    app_state_update_time = UnicodeAttribute()

    @staticmethod
    def make_app_state_hash_key(app_name: str) -> str:
        """
        Create a hash key for the app state in DynamoDB.
        The format is: AppState#<app_name>
        """
        return f"AppState#{app_name}"

    @staticmethod
    def make_app_state_range_key(app_name: str) -> str:
        """
        Create a range key for the app state in DynamoDB.
        The format is: #METADATA#<app_name>
        """
        return f"#METADATA#{app_name}"


class UserStateModel(ADKEntityModel, discriminator="UserState"):
    user_state = UnicodeAttribute()
    user_state_update_time = UnicodeAttribute()

    @staticmethod
    def make_user_state_hash_key(app_name: str, user_id: str) -> str:
        """
        Create a hash key for the user state in DynamoDB.
        The format is: UserState#<app_name>#<user_id>
        """
        return f"UserState#{app_name}#{user_id}"

    @staticmethod
    def make_user_state_range_key(user_id: str) -> str:
        """
        Create a range key for the user state in DynamoDB.
        The format is: #METADATA#<user_id>
        """
        return f"#METADATA#{user_id}"

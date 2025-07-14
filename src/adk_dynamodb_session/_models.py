import pickle
from typing import Any

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

    class Meta:
        table_name = "AdkTable"

    PK = UnicodeAttribute(hash_key=True)
    SK = UnicodeAttribute(range_key=True)

    Type = DiscriminatorAttribute(attr_name="Type")


class SessionModel(ADKEntityModel, discriminator="Session"):
    session_id = UnicodeAttribute()
    session_state = UnicodeAttribute()
    create_time = UnicodeAttribute()
    update_time = UnicodeAttribute()


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

    # some extra attributes for the event that are generally useful
    # but not required by ADK
    user_feedback = UnicodeAttribute(null=True)


class AppStateModel(ADKEntityModel, discriminator="AppState"):
    app_state = UnicodeAttribute()
    app_state_update_time = UnicodeAttribute()


class UserStateModel(ADKEntityModel, discriminator="UserState"):
    user_state = UnicodeAttribute()
    user_state_update_time = UnicodeAttribute()

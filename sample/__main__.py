# ruff: noqa: T201

import argparse
import asyncio
import logging
import os
from typing import Any
from uuid import uuid4

from google.adk.agents import Agent
from google.adk.agents.llm_agent import LlmAgent
from google.adk.events import Event
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.genai.types import Content, Part

from adk_dynamodb_session import DynamoDBSessionService

logger = logging.getLogger("sample_app")


def pretty_print_event(event: Event) -> None:
    logger.debug(f"[{event.author}] event, final: {event.is_final_response()}")

    if not event.content or not event.content.parts:
        return

    for part in event.content.parts:
        if part.text:
            logger.debug(f"  ==> text: {part.text}")
        elif part.function_call:
            func_call = part.function_call
            logger.debug(f"  ==> func_call: {func_call.name}, args: {func_call.args}")
        elif part.function_response:
            func_response = part.function_response
            logger.debug(f"  ==> func_response: {func_response.name}, response: {func_response.response}")


async def call_agent(runner: Runner, user_id: str, session_id: str, query: str) -> None:
    content = Content(role="user", parts=[Part(text=query)])
    response_text = ""

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        pretty_print_event(event)

        if event.is_final_response():
            if event.content and event.content.parts:
                response_text += event.content.parts[0].text
            elif event.actions and event.actions.escalate:
                response_text = f"Agent escalated: {event.error_message or 'No specific message.'}"
            break  # Stop processing events once the final response is found
        # else:
        #     if event.content and event.content.parts and event.content.parts[0].text:
        #         response_text += event.content.parts[0].text

    print(f"<<< Agent: {response_text}")


async def setup_runner(agent: Agent, app_name: str, user_id: str, session_id: str) -> Runner:
    # session_service = InMemorySessionService()  # type:ignore
    # session_service = DatabaseSessionService(db_url="sqlite:///tmp/sample_app.db")
    session_service = DynamoDBSessionService()
    session_service.create_table_if_not_exists()

    await session_service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
    logger.info(f"Session created: App='{app_name}', User='{user_id}', Session='{session_id}'")

    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)
    logger.info(f"Runner created: Agent='{runner.agent.name}'")
    return runner


async def main(args: Any) -> None:
    philosphy_agent = LlmAgent(
        name="mr_philosopher",
        model=LiteLlm(model="ollama_chat/mistral-small3.1:latest"),
        description="A general agent that can talk about philosophy.",
        instruction="""
You are a philosopher with is full of positive energy and always tries to find the good in every situation.
""",
    )

    runner = await setup_runner(philosphy_agent, args.app_name, args.user_id, args.session_id)

    print("Welcome! Start chatting with the agent. Type 'exit' to end.")
    while True:
        query = input(">>> User: ")
        if query.lower() == "exit":
            print("Goodbye!")
            break
        await call_agent(runner, args.user_id, args.session_id, query)


if __name__ == "__main__":
    os.environ["OLLAMA_API_BASE"] = "http://host.docker.internal:11434"
    os.environ["AWS_ACCESS_KEY_ID"] = "1"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "2"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_ENDPOINT_URL_DYNAMODB"] = "http://host.docker.internal:8009"

    parser = argparse.ArgumentParser()
    parser.add_argument("--app-name", default="app1", help="app name")
    parser.add_argument("--user-id", default="user-1", help="user id")
    parser.add_argument("--session-id", default=uuid4().hex, help="session id")
    args = parser.parse_args()

    asyncio.run(main(args))

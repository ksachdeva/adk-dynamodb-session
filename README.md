# DynamoDB as the backed for Session Service

This package provides the implementation of `BaseSessionService` in Google ADK that
uses DynamoDB as the backend

## Install

```bash
uv add adk-dynamodb-session
```

## Sample Application

The sample application is using `Ollama` and the `dynamodb-local`

### Start dynamodb-local using docker

Do this on your machine (not from the dev container)

```bash
cd <path_to_adk_dynamodb_session>/test-data
docker compose -f dynamodb-local.yaml up
```

### Run the sample app

Do this from within the devcontainer

```bash
uv run sample
```

## Run tests (again local DynamoDB)

```bash
uv run poe test
```
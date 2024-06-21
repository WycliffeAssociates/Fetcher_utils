#!/bin/bash

if [ -z "$DEPLOY_ENV" ]; then
  echo "Error: Please set the 'DEPLOY_ENV' environment variable."
  exit 1
fi

if [ -z "$OP_SERVICE_ACCOUNT_TOKEN" ]; then
  echo "Error: Please set the 'OP_SERVICE_ACCOUNT_TOKEN' environment variable."
  exit 1
fi

shopt -s expand_aliases

alias op="docker run --rm -e OP_SERVICE_ACCOUNT_TOKEN 1password/op:2 op"

# Log in to 1password CLI

export OP_SERVICE_ACCOUNT_TOKEN=$OP_SERVICE_ACCOUNT_TOKEN

# Config vars via 1password secret refs

export QUEUE_NAME=audiobiel
export CONTENT_DIR=/content
export CONTENT_URL=https://audio-content.bibleineverylanguage.org/
export NAMESPACE_CONNECTION_STR=$(op read "op://AppDev Scripture Accessibility/languageapi-bus-con/$DEPLOY_ENV/conn_string")

docker compose down
docker compose up
docker compose down

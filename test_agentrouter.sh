#!/usr/bin/env bash
# Does the AgentRouter token work through an approved client?
# Run from the repo root:  bash test_agentrouter.sh
#
# Nothing here spoofs a client. Test 1 is the raw request that already fails
# (kept as the control). Tests 2 and 3 let the vendor's own binary make the call.

set -uo pipefail
cd "$(dirname "$0")"

if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

KEY="${AGENTROUTER_API_KEY:-}"
if [[ -z "$KEY" ]]; then
  echo "AGENTROUTER_API_KEY is empty — set it in .env first." >&2
  exit 1
fi

PROMPT='Reply with exactly one word: pong'

hr() { printf '\n%s\n' "----------------------------------------------------------------"; }

hr
echo "1. CONTROL — raw OpenAI-compatible request (expected: 401 unauthorized_client)"
hr
curl -s -o /tmp/ar_raw.json -w 'HTTP %{http_code}\n' \
  https://agentrouter.org/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"gpt-5\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}]}"
head -c 400 /tmp/ar_raw.json; echo

hr
echo "1b. What models does the key actually see?"
hr
curl -s https://agentrouter.org/v1/models -H "Authorization: Bearer $KEY" | head -c 800; echo

hr
echo "2. Claude Code headless (approved client, unmodified)"
hr
if command -v claude >/dev/null 2>&1; then
  env ANTHROPIC_BASE_URL="https://agentrouter.org/" \
      ANTHROPIC_AUTH_TOKEN="$KEY" \
      ANTHROPIC_API_KEY="$KEY" \
      ANTHROPIC_MODEL="claude-haiku-4-5-20251001" \
    claude --bare -p "$PROMPT" --output-format json 2>&1 | head -c 1200
  echo
else
  echo "claude not installed.  npm install -g @anthropic-ai/claude-code"
fi

hr
echo "3. Codex headless (approved client, unmodified)"
hr
if command -v codex >/dev/null 2>&1; then
  if [[ ! -f "$HOME/.codex/config.toml" ]]; then
    echo "~/.codex/config.toml missing. Create it with:"
    cat <<'TOML'
model = "gpt-5"
model_provider = "openai-chat-completions"
preferred_auth_method = "apikey"

[model_providers.openai-chat-completions]
name = "OpenAI using Chat Completions"
base_url = "https://agentrouter.org/v1"
env_key = "AGENT_ROUTER_TOKEN"
wire_api = "chat"
stream_idle_timeout_ms = 300000
TOML
  else
    env AGENT_ROUTER_TOKEN="$KEY" codex exec "$PROMPT" 2>&1 | head -c 1200
    echo
  fi
else
  echo "codex not installed.  npm install -g @openai/codex"
fi

hr
echo "Read it like this:"
echo "  1 fails, 2 or 3 succeeds  -> the gate is on the client. Subprocess backend works."
echo "  everything fails          -> the token or the account is the problem, not the client."
echo "  1 succeeds                -> they lifted the gate; the plain HTTP profile is fine as-is."
hr

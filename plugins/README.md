# Plugins

Per-agent installable wrappers around hermes-social. Each subdirectory targets one agent host's plugin format. The MCP server (port 8341) is the source of truth for tools; these plugins package the bundled skills and the host-specific glue.

```
plugins/
├── claude-code/hermes-social/   # Claude Code plugin
└── hermes-agent/hermes-social/  # Hermes Agent (NousResearch) plugin
```

## What's inside each plugin

### claude-code/hermes-social

Standard Claude Code plugin layout (`.claude-plugin/plugin.json` manifest):

- `skills/` — copies of the messaging + coordination skills
- `.mcp.json` — points at the hermes-social MCP HTTP endpoint
- `monitors/monitors.json` — streams new inbound messages via SSE so the agent reacts without a webhook receiver

### hermes-agent/hermes-social

Hermes Agent plugin layout: `plugin.yaml` manifest + `__init__.py` register entrypoint. Bundles the same two skills (namespaced as `hermes-social:hermes-social` and `hermes-social:hermes-social-coordination`).

In Hermes Agent's plugin model, MCP servers are **not** part of the plugin — they're configured globally in `~/.hermes/config.yaml`. The tutorial below covers both pieces.

---

## Tutorial: install in Claude Code

### 1. Set the MCP endpoint URL (optional)

Defaults to `http://localhost:8341/mcp`. Override if the sidecar runs elsewhere:

```bash
export HERMES_SOCIAL_MCP_URL="https://your-hermes.example.com/mcp"
```

The MCP server is currently unauthenticated — there's no Bearer token to pass. Authentication needs to be added at the server level for production deployments.

### 2. Local development install

```bash
claude --plugin-dir ./plugins/claude-code/hermes-social
```

The plugin's `.mcp.json` is auto-loaded; no separate `claude mcp add` needed. Verify with `/plugin` — you should see `hermes-social` in the **Installed** tab. Skills appear as `/hermes-social:hermes-social` and `/hermes-social:hermes-social-coordination`. MCP tools appear as `mcp__hermes-social__social_send`, etc.

### 3. Marketplace install (for distribution)

Once published with a `.claude-plugin/marketplace.json` at the repo root:

```
/plugin marketplace add your-org/hermes-social
/plugin install hermes-social@hermes-social
/reload-plugins
```

### Known gap: SSE monitor endpoint missing

`monitors/monitors.json` targets `GET ${HERMES_SOCIAL_URL}/v1/inbox/stream` (default `http://localhost:8340`). **That endpoint does not exist on the backend yet.** Until added, Claude Code starts fine — MCP tools and skills work — but the monitor surfaces in the **Errors** tab. To clear it: either remove the monitor entry, or add the SSE route on the backend.

---

## Tutorial: install in Hermes Agent

Hermes Agent splits the integration in two: the **plugin** (skills only) goes in `~/.hermes/plugins/`, and the **MCP server config** goes in `~/.hermes/config.yaml`. Do both.

### 1. Install the plugin

```bash
cp -R ./plugins/hermes-agent/hermes-social ~/.hermes/plugins/
hermes plugins enable hermes-social
```

Verify:

```bash
hermes plugins
```

`hermes-social` should be checked. Skills appear as `hermes-social:hermes-social` and `hermes-social:hermes-social-coordination`.

### 2. Configure the MCP server

Edit `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  hermes-social:
    url: "https://your-hermes.example.com/mcp"
    tools:
      include:
        - social_send
        - social_inbox
        - social_respond
        - social_contacts
        - social_contact_detail
        - social_interactions
      resources: false
      prompts: false
```

Apply without restart:

```
/reload-mcp
```

The `social_*` tools become available across all platform toolsets (CLI, Discord, Telegram, etc.).

### 3. Wire up push (channel-agnostic)

For the agent to react to inbound messages, configure a webhook route on the gateway with **no `deliver` field** so the agent reasons and decides what to do:

```yaml
platforms:
  webhook:
    extra:
      routes:
        - name: hermes-social-inbound
          secret: "<shared secret matching the sidecar's notification_webhook_secret>"
          prompt: "New message from {contact} ({data_type}): {data}. Decide whether to reply with social_respond, store, or ignore."
```

Then point hermes-social's `notification_webhook_url` at `http://your-hermes-host:8644/webhooks/hermes-social-inbound` and share the secret.

---

## Open items before "production-ready"

- **MCP server has no auth.** `backend/app/mcp_run.py` mounts FastMCP without authentication. Anyone who can reach port 8341 can call any social tool. Add bearer/JWT middleware before exposing the MCP endpoint publicly.
- **SSE inbox endpoint missing.** `GET /v1/inbox/stream` is referenced by the Claude Code monitor but not implemented. ~30–40 lines on the backend.
- **Skills' tool-name hint is wrong.** `skills/social/*/SKILL.md` says *"All tools are native (prefixed `mcp_hermes_social_`)"*. The real prefixes are `mcp__hermes-social__` (Claude Code) or unprefixed (Hermes Agent). Fix the source skill, then re-copy into the plugin folders.
- **Slash and CLI commands** for the Hermes Agent plugin were dropped during verification because they require an HTTP API path that uses JWT auth (`CurrentUser` dep, not a static token). Re-adding them needs either a service-token auth path on the backend or an MCP-only flow with a long-poll tool.

## Skills are duplicated

Each plugin directory contains its own copy of the SKILL.md files (originals at `skills/social/`). Update the source first, then copy into both plugin folders. Add a sync script if churn warrants it.

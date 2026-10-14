# Security

## Reporting a problem

Please report security problems privately, not in a public issue. Use GitHub's
**Security > Report a vulnerability** form on this repository. You will get an answer within a week.

Include what you found, how to reproduce it and what an attacker could do with it.

## Never post secrets

Never paste these in an issue, a pull request, a discussion or a log excerpt:

- `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` or anything else from `.env`
- your Telegram chat id, server address or SSH keys
- your CV or `profile.yml` if it contains personal details

`jobbot check-config` output is safe to share: it only says whether each secret is set.

If a token leaked, rotate it right away: `/revoke` in @BotFather for Telegram, and delete and recreate the key in Google AI Studio or the Anthropic console.

## Design notes

- The bot only makes outbound requests. It opens no ports.
- Telegram commands and buttons are obeyed only from the configured chat id.
- The systemd unit runs as an unprivileged user with a read-only system and write access to `data/` only.
- Secrets live only in `.env`, which is gitignored and copied to a server only with `deploy.sh --with-secrets` (mode 600).

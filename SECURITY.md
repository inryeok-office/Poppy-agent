# Security

Never commit secrets or site-specific robot configuration. This includes agent
tokens, `X-Agent-Token` values, robot IP addresses, Wi-Fi credentials, SSH keys,
GitHub tokens, Unitree credentials, and production network settings.

Use environment variables for local values. `.env` files are ignored; `.env.example`
contains names and non-secret placeholders only. Do not print credentials in logs,
errors, tests, Issues, pull requests, or documentation.

Report a suspected credential exposure privately to the repository maintainers rather
than opening a public Issue.


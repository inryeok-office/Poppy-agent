# Architecture

The repository is intentionally small while the runtime contract is being established.

```text
src/poppy_agent/
└── main.py
```

Future layers should be added only when an approved Issue needs them. The planned
boundaries are configuration, agent lifecycle, robot adapters, and a Poppy-Server
client. Robot control methods are outside the current automation scope.


# Security policy

## Reporting a vulnerability

Please **don't open a public issue**. Use GitHub's private reporting: **Security → Report a vulnerability** on this repository. You'll get a reply as soon as possible, usually within a few days.

Helpful details: what you found, steps to reproduce, and the impact.

## Scope

- The live app at https://unbluffable-ptz1.onrender.com and the code in this repository.
- API keys are held only on the server and never sent to the browser; realtime voice authenticates through a server relay. Reports of key exposure are the highest priority.
- User-supplied questions ("bring your own question") run generated solver code in a sandbox; sandbox escapes are in scope.

## Supported versions

Only the latest `main` is supported.

# Security Policy

## Supported versions

Security fixes are applied on the default branch (`main`) of this repository.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Email or message the maintainer via GitHub (user `evan66547`) with:
- a short description of the issue
- steps to reproduce (if safe to share)
- impact assessment if known

We will acknowledge reports when possible and coordinate a fix before any public disclosure.

## Safe use notes

- Do not commit secrets, API keys, or personal case data.
- Treat uploaded documents / OCR inputs as sensitive.
- Prefer local / self-hosted modes when handling confidential material.

## Extra notes for this project

- OCR frames and target lists may contain personal or commercial secrets; keep them local.
- Do not commit `config.json`, live `targets.json`, or scan logs.

# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take the security of Bantz seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via one of the following methods:

1. **GitHub Private Vulnerability Reporting** (Preferred)
   - Go to the Security tab of this repository
   - Click "Report a vulnerability"
   - Fill out the form with details

2. **Direct Contact**
   - GitHub: [@miclaldogan](https://github.com/miclaldogan)
   - Create a private gist and share the link

### What to Include

Please include the following information in your report:

- **Type of vulnerability** (e.g., command injection, path traversal, XSS)
- **Location** of the affected source code (file path, line numbers)
- **Step-by-step instructions** to reproduce the issue
- **Proof-of-concept** or exploit code (if possible)
- **Impact** of the vulnerability
- **Suggested fix** (if you have one)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Resolution Target**: Within 30 days (depending on complexity)

### Safe Harbor

We consider security research conducted in accordance with this policy to be:

- Authorized and we will not initiate legal action
- Conducted in good faith
- Helpful to improving the security of Bantz

### Scope

The following are in scope for security research:

- ✅ Voice command injection
- ✅ Unauthorized file system access
- ✅ Browser extension security
- ✅ WebSocket communication security
- ✅ LLM prompt injection
- ✅ Privilege escalation
- ✅ Data exposure/leakage

The following are out of scope:

- ❌ Social engineering attacks
- ❌ Physical attacks
- ❌ Denial of service attacks
- ❌ Issues in third-party dependencies (report to them directly)

## Security Best Practices for Users

When using Bantz, please follow these security guidelines:

1. **Never run Bantz as root/administrator**
2. **Review policy.json** before enabling dangerous commands
3. **Keep dependencies updated** (`pip install --upgrade bantz`)
4. **Use a dedicated browser profile** for Bantz
5. **Be cautious with voice commands** that modify files or execute code

## Known Security Considerations

| Area | Risk | Mitigation |
|------|------|------------|
| Voice Commands | Command injection | NLU validation, policy.json allowlists |
| Browser Control | Unauthorized actions | Confirmation gates, URL allowlists |
| File Operations | Path traversal | Sandboxed directories, policy rules |
| LLM Integration | Prompt injection | Input sanitization, output validation |
| WebSocket | MITM attacks | Localhost-only binding |

---

Thank you for helping keep Bantz and its users safe! 🛡️

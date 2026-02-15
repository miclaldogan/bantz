# Contributing to Bantz

Thanks for wanting to contribute to Bantz! 🎉

This document explains how you can contribute to the project step by step.

---

## 🚀 Quick Start

### 1. Clone the repo

```bash
git clone git@github.com:miclaldogan/bantz.git
cd bantz
```

### 2. Set up the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/all.txt
pip install -e .
```

### 3. Run the tests

```bash
pytest tests/ -v --tb=short
```

If all tests pass, you’re ready to start coding! ✅

---

## 🌳 Branch Rules

| Branch                        | Purpose                                         |
| ----------------------------- | ----------------------------------------------- |
| `main`                        | Stable release — do not push directly           |
| `dev`                         | Active development — all PRs target this branch |
| `fix/XXX-short-description`   | Bug fix branches                                |
| `feat/XXX-short-description`  | Feature branches                                |
| `chore/XXX-short-description` | Refactors, cleanup, CI/CD                       |

### Create a new branch

```bash
git checkout dev
git pull origin dev
git checkout -b fix/123-short-description dev
```

> ⚠️ **Always branch off `dev`. Never create branches from `main`.**

---

## ✍️ Commit Messages

We use the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
type(scope): short description (#issue-no)
```

### Types

|       Type | Use                                      |
| ---------: | ---------------------------------------- |
|      `fix` | Bug fix                                  |
|     `feat` | New feature                              |
| `refactor` | Code improvement without behavior change |
|     `test` | Add/fix tests                            |
|     `docs` | Documentation                            |
|    `chore` | CI/CD, dependencies, configuration       |

### Examples

```
fix(voice): guard barge-in state with threading.Lock (#759)
feat(calendar): add all-day event detection (#750)
test(scheduler): add ReminderManager unit tests (#758)
refactor(privacy): tighten IP regex to reject version strings (#748)
```

---

## 🔀 Pull Request Process

1. **Create your branch** and make your changes
2. **Run the tests** — don’t open a PR with failing tests
3. **Push** and open a PR against the `dev` branch
4. Fill out the PR template completely
5. Wait for review — at least **1 approval** is required
6. After merge, the branch is automatically deleted

### PR Checklist

* [ ] Tests pass (`pytest tests/ -v`)
* [ ] Tests were added for new code
* [ ] Commit messages follow the conventional format
* [ ] Related issue is linked (`Closes #XXX`)

---

## 🧪 Testing Rules

* Write tests for every new feature/fix
* Test files: `tests/test_<module_name>.py`
* We use `pytest`, not `unittest`
* Use the `tmp_path` fixture — don’t hardcode paths
* Empty assertions like `assert True` are forbidden — verify real values

```bash
# Run a single test file
pytest tests/test_scheduler.py -v

# Run a specific test
pytest tests/test_ipc.py::TestEncoding::test_roundtrip_state -v
```

---

## 📁 Project Structure

```
src/bantz/
├── brain/          # LLM orchestration, tiered quality
├── core/           # Event bus, config, plugin system
├── google/         # Calendar, Gmail integration
├── ipc/            # Browser overlay IPC protocol
├── privacy/        # PII redaction, data masking
├── router/         # Intent routing, policy engine
├── scheduler/      # Reminders, check-ins
├── security/       # Action classifier, audit, permissions
├── tools/          # Tool registry, result formatting
└── voice/          # TTS, STT, wake word, barge-in, FSM
```

---

## 🎨 Code Style

* **Python 3.10+** — use type hints
* **Docstrings**: Google style
* **Line length**: 100 characters (soft limit)
* **Import order**: stdlib → third-party → local
* **Language**: Code and variable names in English; user-facing strings in Turkish

```python
def _parse_time(self, time_str: str) -> Optional[datetime]:
    """Parse Turkish time string like '5 dakika sonra' or 'yarın 09:00'."""
    ...
```

---

## 🔒 Security

If you find a security vulnerability, **do not open an issue** — instead follow the instructions in [SECURITY.md](SECURITY.md).

---

## 💬 Communication

* Use [GitHub Discussions](https://github.com/miclaldogan/bantz/discussions) for questions
* For bug reports, [open an issue](https://github.com/miclaldogan/bantz/issues/new?template=bug_report.md)

---

Welcome aboard, and happy coding! 🚀

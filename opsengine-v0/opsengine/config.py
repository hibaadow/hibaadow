"""Settings from the environment, with an optional .env file in the project root.

Values already set in the real environment always win over .env. See .env.example."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUE = {"1", "true", "yes", "on"}


def load_dotenv(path=ROOT / ".env"):
    """Read KEY=VALUE lines into os.environ without overriding anything already set."""
    path = Path(path)
    if not path.exists():
        return {}
    loaded = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def flag(name):
    return os.environ.get(name, "").strip().lower() in TRUE


def mock_ai():
    """USE_MOCK_AI=true: never call Claude. Sample photos get recorded reads; nothing else is faked."""
    return flag("USE_MOCK_AI")

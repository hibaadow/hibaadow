import os

os.environ.setdefault("ATLAS_DATABASE_URL", os.environ.get("ATLAS_TEST_DATABASE_URL", "postgresql+psycopg://atlas:atlas_dev_pw@localhost:5432/atlas_test"))
os.environ["ATLAS_ENV"] = "test"
os.environ["ATLAS_REDIS_URL"] = ""
os.environ["ATLAS_EMBEDDED_WORKER"] = "false"
os.environ["ATLAS_ENABLE_WEBSOCKETS"] = "false"
os.environ["ATLAS_ADMIN_PASSWORD"] = "test-admin-password"
os.environ.pop("ANTHROPIC_API_KEY", None)

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from atlas import db as dbmod  # noqa: E402
from atlas.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    from atlas import models  # noqa: F401

    eng = dbmod.configure(os.environ["ATLAS_DATABASE_URL"])
    with eng.begin() as c:
        c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    dbmod.init_db()  # exercises the Alembic migrations
    yield


@pytest.fixture(autouse=True)
def _clean():
    from atlas.events import LocalBus, set_bus

    set_bus(LocalBus())
    eng = dbmod.engine()
    with eng.begin() as c:
        tables = ", ".join(t.name for t in dbmod.Base.metadata.sorted_tables)  # alembic_version is preserved
        c.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    yield


@pytest.fixture
def db():
    with dbmod.session_scope() as s:
        yield s


def make_series(closes, symbol="SOLUSDC", tf="5m", start=1_700_000_100_000 // 300_000 * 300_000, vol=None, spread=0.002):
    from atlas.marketdata.types import TF_MS, Candle, CandleSeries

    step = TF_MS[tf]
    closes = list(closes)
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        h = max(o, c) * (1 + spread / 2)
        l = min(o, c) * (1 - spread / 2)
        v = (vol[i] if vol is not None else 1000.0)
        out.append(Candle(start + i * step, o, h, l, c, v, v * c))
        prev = c
    return CandleSeries.from_candles(symbol, tf, "test", out), out


@pytest.fixture
def series_factory():
    return make_series


def rng_walk(n=800, seed=1, drift=0.0, vol=0.004, p0=100.0):
    r = np.random.default_rng(seed)
    return p0 * np.exp(np.cumsum(r.normal(drift, vol, n)))

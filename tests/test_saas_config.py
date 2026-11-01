from app.saas.config import engine_options


def test_sqlite_database_options_keep_thread_sharing_enabled():
    options = engine_options("sqlite:///./gst_billing.db")
    assert options["future"] is True
    assert options["pool_pre_ping"] is True
    assert options["connect_args"] == {"check_same_thread": False}


def test_postgres_database_options_do_not_use_sqlite_arguments():
    options = engine_options(
        "postgresql+psycopg://user:password@localhost:5432/erp"
    )
    assert options["future"] is True
    assert options["pool_pre_ping"] is True
    assert "connect_args" not in options

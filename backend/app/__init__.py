__all__ = ["app"]


def __getattr__(name: str):
    # Lazy so importing the package (e.g. app.config in tests) does not build
    # the database engine before settings/env are finalized.
    if name == "app":
        from app.main import app

        return app
    raise AttributeError(f"module 'app' has no attribute {name!r}")

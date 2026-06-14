import logging
import sys
import warnings


LOG_LEVELS = {
    # === Robo app modules ===
    "app":                      logging.DEBUG,
    "app.main":                 logging.INFO,
    "app.config":               logging.INFO,
    "app.api":                  logging.INFO,
    "app.api.health":           logging.INFO,
    "app.db":                   logging.INFO,
    "app.db.session":           logging.INFO,
    "app.db.models":            logging.DEBUG,
    "app.voice":                logging.DEBUG,
    "app.voice.ws_handler":     logging.DEBUG,
    "app.voice.vad":            logging.INFO,
    "app.voice.stt":            logging.INFO,
    "app.voice.tts":            logging.INFO,
    "app.session":              logging.INFO,
    "app.session.manager":      logging.INFO,
    "app.agent":                logging.DEBUG,
    "app.tools":                logging.DEBUG,
    "app.notifications":        logging.DEBUG,

    # === Third-party — quiet ===
    "torch":                        logging.WARNING,
    "torch.hub":                    logging.WARNING,
    "torchvision":                  logging.WARNING,
    "torchaudio":                   logging.WARNING,
    "pytorch_lightning":            logging.WARNING,
    "numpy":                        logging.WARNING,
    "urllib3":                      logging.WARNING,
    "sqlalchemy":                   logging.WARNING,
    "sqlalchemy.engine":            logging.WARNING,
    "sqlalchemy.orm":               logging.WARNING,
    "alembic":                      logging.WARNING,   # kills "setup plugin" spam
    "alembic.runtime.migration":    logging.INFO,      # keep actual migration lines
    "redis":                        logging.WARNING,
    "httpx":                        logging.WARNING,
    "httpcore":                     logging.WARNING,
    "websockets":                   logging.WARNING,
    "asyncio":                      logging.WARNING,
    "fastapi":                      logging.WARNING,
    "starlette":                    logging.WARNING,
    "uvicorn":                      logging.WARNING,   # uvicorn prints its own banner
    "uvicorn.access":               logging.WARNING,
    "watchfiles":                   logging.WARNING,   # suppress .venv change detection spam
    "transformers":                 logging.WARNING,
    "huggingface_hub":              logging.WARNING,
    "requests":                     logging.WARNING,
    "urllib":                       logging.WARNING,
    "asyncpg":                      logging.WARNING,
    "py.warnings":                  logging.WARNING,   # torch UserWarning / FutureWarning
}


def setup_logging() -> None:
    """
    Call once at the very top of main.py before any other imports.
    Writes to stdout (same stream as uvicorn) so output stays in order.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Clear any handlers already attached (safe for uvicorn --reload)
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-8s %(name)s : %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(handler)

    for name, level in LOG_LEVELS.items():
        logging.getLogger(name).setLevel(level)

    # Route Python warnings through logging (so py.warnings level above applies)
    logging.captureWarnings(True)

    # Belt-and-braces: also suppress at warnings filter level
    warnings.filterwarnings("ignore", category=UserWarning,  module=r"torch.*")
    warnings.filterwarnings("ignore", category=FutureWarning, module=r"torch.*")
    warnings.filterwarnings("ignore", message=r".*Defaulting repo_id.*")
    warnings.filterwarnings("ignore", message=r".*dropout option.*")
    warnings.filterwarnings("ignore", message=r".*weight_norm.*")

    logging.getLogger("app.main").info("Logging ready — app=DEBUG/INFO, libs=WARNING")


def suppress_library_spam() -> None:
    """Optional extra suppression; call after setup_logging()."""
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("silero_vad").setLevel(logging.WARNING)

    try:
        import transformers
        transformers.logging.set_verbosity_error()
    except Exception:
        pass

    try:
        import huggingface_hub
        huggingface_hub.logging.set_verbosity_error()
    except Exception:
        pass


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

"""Load agent/.env so integration tests can read real credentials when opted in."""
import os

try:
    from dotenv import load_dotenv

    _ENV = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".env",
    )
    load_dotenv(_ENV)
except Exception:
    pass

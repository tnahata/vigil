"""Vigil EMT voice-copilot agent package.

Layout (hexagonal -- the dose path is structurally LLM-free):
  vigil.core      pure logic; MUST NOT import livekit/openai/moss/minimax
                  (enforced by tests/test_core_purity.py)
  vigil.ports     interfaces (Protocols) for the outside world
  vigil.adapters  concrete impls: fakes for tests, real adapters for the worker
  vigil.config    env/model-name loading (kept out of core)
"""

__version__ = "0.1.0"

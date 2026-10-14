"""Nally Agent Package - Lazy imports to avoid startup hangs"""


def get_agent():
    """Lazy singleton for NallyAgent (avoids import-time DB/cloud init)"""
    from .core import get_agent as _get_agent

    return _get_agent()


def get_session_manager():
    """Lazy accessor for session manager"""
    from .sessions import session_manager

    return session_manager


def get_llm():
    """Lazy accessor for LLM client"""
    from .llm import llm

    return llm


__all__ = ["get_agent", "get_llm", "get_session_manager"]

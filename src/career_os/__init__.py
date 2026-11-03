"""Career OS: local-first, model-agnostic career data system.

This package contains no CLI-specific or Claude-specific logic in its
service layer. Any client (CLI, MCP, a different LLM, a script) should
be able to call career_os.services.* and get the same behavior.
"""

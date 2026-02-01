"""LLM Client Interface - Backend abstraction for vLLM (OpenAI-compatible).

Issue #133: Backend Abstraction

This module provides a unified interface for the project's LLM backend.

Project policy (2026-02): vLLM (OpenAI-compatible API) is the supported local
inference backend.

Design goals:
- Single interface for BrainLoop/Router
- Config-based backend selection
- Easy to test (mock clients)
- Consistent error handling
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Protocol


@dataclass(frozen=True)
class LLMMessage:
    """Standard message format for all LLM clients."""
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResponse:
    """Standard response from LLM client."""
    content: str  # Generated text
    model: str  # Model used
    tokens_used: int  # Total tokens (prompt + completion)
    finish_reason: str  # "stop" | "length" | "error"


class LLMClientError(Exception):
    """Base exception for LLM client errors."""
    pass


class LLMConnectionError(LLMClientError):
    """Server connection failed."""
    pass


class LLMModelNotFoundError(LLMClientError):
    """Requested model not available."""
    pass


class LLMTimeoutError(LLMClientError):
    """Request timed out."""
    pass


class LLMInvalidResponseError(LLMClientError):
    """Response parsing failed."""
    pass


class LLMClient(ABC):
    """Abstract base class for LLM clients.

    Concrete clients must implement this interface.
    """
    
    @abstractmethod
    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        """Check if backend is reachable.
        
        Args:
            timeout_seconds: Connection timeout
            
        Returns:
            True if backend responds
        """
        pass
    
    @abstractmethod
    def chat(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
    ) -> str:
        """Chat completion (simple string response).
        
        Args:
            messages: Conversation history
            temperature: Sampling temperature (0.0 = deterministic)
            max_tokens: Max tokens to generate
            
        Returns:
            Generated text
            
        Raises:
            LLMConnectionError: Cannot reach backend
            LLMModelNotFoundError: Model not available
            LLMTimeoutError: Request timed out
            LLMInvalidResponseError: Response parsing failed
        """
        pass
    
    @abstractmethod
    def chat_detailed(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
        seed: Optional[int] = None,
    ) -> LLMResponse:
        """Chat completion (detailed response with metadata).
        
        Args:
            messages: Conversation history
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            seed: Random seed for determinism
            
        Returns:
            LLMResponse with content and metadata
            
        Raises:
            Same as chat()
        """
        pass
    
    @abstractmethod
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        """Simple text completion (used by Router).
        
        Args:
            prompt: Single prompt string
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            
        Returns:
            Generated text
            
        Raises:
            Same as chat()
        """
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Current model name."""
        pass
    
    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Backend type: 'vllm', etc."""
        pass


class LLMClientProtocol(Protocol):
    """Protocol for type checking (duck typing).
    
    Use this for type hints when you don't need ABC enforcement.
    """
    
    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        ...
    
    def chat(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
    ) -> str:
        ...
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        ...
    
    @property
    def model_name(self) -> str:
        ...
    
    @property
    def backend_name(self) -> str:
        ...


def create_client(
    backend: str,
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 120.0,
) -> LLMClient:
    """Factory function to create LLM client.
    
    Args:
        backend: 'vllm' | 'gemini' | 'openai'
        base_url: Backend URL (optional, uses defaults)
        model: Model name (optional, uses defaults)
        timeout: Request timeout
        
    Returns:
        Concrete LLMClient implementation
        
    Raises:
        ValueError: Unknown backend
        
    Example:
        >>> client = create_client('vllm', base_url='http://localhost:8001')
    """
    backend = backend.lower().strip()

    if backend == "vllm":
        from bantz.llm.vllm_openai_client import VLLMOpenAIClient
        return VLLMOpenAIClient(
            base_url=base_url or "http://127.0.0.1:8001",
            model=model or "Qwen/Qwen2.5-3B-Instruct",
            timeout_seconds=timeout,
        )

    if backend == "gemini":
        # Gemini uses an API key (not base_url). Pass the key via base_url for factory parity.
        # Prefer using bantz.llm.create_quality_client() which applies privacy gating.
        from bantz.llm.gemini_client import GeminiClient

        api_key = (base_url or "").strip()
        return GeminiClient(
            api_key=api_key,
            model=model or "gemini-1.5-flash",
            timeout_seconds=timeout,
        )
    
    elif backend == "openai":
        # Future: OpenAI API client
        raise NotImplementedError("OpenAI backend not yet implemented")

    raise ValueError(f"Unknown backend: {backend}")

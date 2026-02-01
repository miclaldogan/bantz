"""LLM Command Rewriter for Bantz.

Uses vLLM (OpenAI-compatible API) to normalize and correct ASR output into clean
commands. This is used in the voice pipeline to improve recognition accuracy.
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Tuple
from dataclasses import dataclass

from bantz.llm.base import LLMClientProtocol, LLMMessage, create_client

logger = logging.getLogger(__name__)

# System prompt for command rewriting
REWRITE_SYSTEM_PROMPT = """Sen bir asistan komut düzeltici sistemsin. 
Görevin: Kullanıcının söylediği komutu düzeltmek ve normalize etmek.

KURALLAR:
1. Sadece komutu düzelt, yeni komut ekleme
2. Türkçe komutları Türkçe tut
3. Web siteleri için tam isim kullan (örn: "yutup" → "youtube")
4. Uygulama isimlerini düzelt (örn: "diskort" → "discord")
5. Sayıları rakam yap (örn: "beş" → "5")
6. Çıktı tek satır olsun
7. Anlaşılmayan kısımları tahmin etme, olduğu gibi bırak

ÖRNEKLER:
- "yutup aç" → "youtube aç"
- "diskort a geç" → "discord'a geç"
- "hatırlat iki dakika sonra su iç" → "hatırlat 2 dakika sonra su iç"
- "sayfayı tarak" → "sayfayı tara"
- "aşa kaydır" → "aşağı kaydır"
- "beşe tıkla" → "5'e tıkla"
- "dak aç" → "duck aç"

Sadece düzeltilmiş komutu yaz, başka bir şey yazma."""


@dataclass
class RewriteResult:
    """Result of LLM rewrite operation."""
    original: str
    rewritten: str
    changed: bool
    latency_ms: float
    
    @property
    def text(self) -> str:
        return self.rewritten


class CommandRewriter:
    """LLM-based command rewriter for ASR output normalization."""
    
    def __init__(
        self,
        model: str = "Qwen/Qwen2.5-3B-Instruct",
        base_url: str = "http://127.0.0.1:8001",
        timeout: float = 10.0,
        enabled: bool = True,
    ):
        self.enabled = enabled
        self._client: Optional[LLMClientProtocol] = None
        self._model = model
        self._base_url = base_url
        self._timeout = timeout
        self._warmed_up = False
    
    def _get_client(self) -> LLMClientProtocol:
        """Lazy initialize client."""
        if self._client is None:
            self._client = create_client(
                "vllm",
                base_url=self._base_url,
                model=self._model,
                timeout=self._timeout,
            )
        return self._client
    
    def warmup(self) -> bool:
        """Warm up the LLM model to reduce first-request latency."""
        if self._warmed_up or not self.enabled:
            return True
        
        try:
            logger.info("[LLM] Warming up rewriter...")
            start = time.perf_counter()
            
            client = self._get_client()
            client.chat(
                [LLMMessage(role="user", content="test")],
                temperature=0.1,
                max_tokens=10,
            )
            
            latency = (time.perf_counter() - start) * 1000
            logger.info(f"[LLM] Warmup complete in {latency:.0f}ms")
            self._warmed_up = True
            return True
            
        except Exception as e:
            logger.warning(f"[LLM] Warmup failed: {e}")
            return False
    
    def rewrite(self, text: str) -> RewriteResult:
        """Rewrite/normalize a command using LLM.
        
        Args:
            text: Raw ASR output text
            
        Returns:
            RewriteResult with original and rewritten text
        """
        if not self.enabled or not text.strip():
            return RewriteResult(
                original=text,
                rewritten=text,
                changed=False,
                latency_ms=0.0,
            )
        
        start = time.perf_counter()
        
        try:
            client = self._get_client()
            
            messages = [
                LLMMessage(role="system", content=REWRITE_SYSTEM_PROMPT),
                LLMMessage(role="user", content=text),
            ]
            
            response = client.chat(
                messages,
                temperature=0.1,  # Low temperature for consistent output
                max_tokens=100,   # Short response expected
            )
            
            # Clean up response
            rewritten = response.strip()
            
            # Remove any quotes or markdown
            if rewritten.startswith('"') and rewritten.endswith('"'):
                rewritten = rewritten[1:-1]
            if rewritten.startswith("'") and rewritten.endswith("'"):
                rewritten = rewritten[1:-1]
            if rewritten.startswith("`") and rewritten.endswith("`"):
                rewritten = rewritten[1:-1]
            
            # Take only first line if multiple
            if "\n" in rewritten:
                rewritten = rewritten.split("\n")[0].strip()
            
            latency = (time.perf_counter() - start) * 1000
            changed = rewritten.lower() != text.lower()
            
            if changed:
                logger.info(f"[LLM] Rewrite: '{text}' → '{rewritten}' ({latency:.0f}ms)")
            else:
                logger.debug(f"[LLM] No change needed ({latency:.0f}ms)")
            
            return RewriteResult(
                original=text,
                rewritten=rewritten,
                changed=changed,
                latency_ms=latency,
            )
            
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.warning(f"[LLM] Rewrite failed: {e} ({latency:.0f}ms)")
            
            # Return original on failure
            return RewriteResult(
                original=text,
                rewritten=text,
                changed=False,
                latency_ms=latency,
            )
    
    def is_available(self) -> bool:
        """Check if LLM service is available."""
        if not self.enabled:
            return False
        
        try:
            import requests
            r = requests.get(
                f"{self._base_url}/api/tags",
                timeout=2.0,
            )
            return r.status_code == 200
        except Exception:
            return False


# Global instance
_rewriter: Optional[CommandRewriter] = None


def get_rewriter(
    enabled: bool = True,
    model: str = "qwen2.5:3b-instruct",
) -> CommandRewriter:
    """Get or create the global command rewriter."""
    global _rewriter
    if _rewriter is None:
        _rewriter = CommandRewriter(model=model, enabled=enabled)
    return _rewriter


def rewrite_command(text: str) -> RewriteResult:
    """Convenience function to rewrite a command."""
    return get_rewriter().rewrite(text)

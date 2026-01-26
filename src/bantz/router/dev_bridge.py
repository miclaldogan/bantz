from __future__ import annotations

from bantz.router.context import ConversationContext
from bantz.router.types import RouterResult


class DevBridge:
    """v0.1.2 stub bridge.

    v0.1.3+: OpenHands / Open Interpreter entegrasyonu buraya takılacak.
    """

    def handle(self, text: str, ctx: ConversationContext) -> RouterResult:
        ctx.last_intent = "dev_task"
        return RouterResult(
            ok=True,
            intent="dev_task",
            user_text=(
                "Görevi aldım. Dev Bridge şu an stub; henüz bir şey çalıştırmıyorum. "
                "İstersen görevi daha spesifik söyle veya 'normal moda dön'. "
                "Başka ne yapayım?"
            ),
            data={"bridge": "dev_stub", "text": text},
        )

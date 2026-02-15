"""Batch draft manager — bulk draft generation and review.

Issue #1294: Kontrollü Mesajlaşma — toplu yanıt hazırlama.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from bantz.messaging.channel import ChannelConnector
from bantz.messaging.models import (Draft, DraftBatch, DraftDecision, Message,
                                    SendResult)

logger = logging.getLogger(__name__)

# LLM reply generator callback type.
DraftGeneratorFn = Callable[[Message, str], Awaitable[str]]


async def _default_draft_generator(message: Message, instruction: str) -> str:
    """Fallback draft generator when no LLM callback is provided."""
    return (
        f"Merhaba,\n\n"
        f"'{message.subject}' konulu mesajınız alındı. "
        f"En kısa sürede detaylı yanıt vereceğim.\n\n"
        f"İyi günler."
    )


class BatchDraftManager:
    """Generate, review, and send message drafts in bulk.

    Typical flow:
        1. ``generate_drafts(messages, instruction)`` — LLM creates drafts
        2. User reviews via ``batch.as_display()``
        3. ``approve(draft_id)`` / ``skip(draft_id)`` / ``edit(draft_id, …)``
        4. ``send_approved(batch)`` — deliver all approved drafts
    """

    def __init__(
        self,
        channel: ChannelConnector,
        draft_generator: DraftGeneratorFn | None = None,
    ) -> None:
        self._channel = channel
        self._generator: DraftGeneratorFn = (
            draft_generator or _default_draft_generator
        )

    # ── draft generation ─────────────────────────────────────────

    async def generate_drafts(
        self,
        messages: list[Message],
        instruction: str = "Kısa ve profesyonel yanıt yaz",
    ) -> DraftBatch:
        """Generate a draft reply for each message using the LLM callback.

        Args:
            messages: Source messages to reply to.
            instruction: Tone / style instruction for the LLM.

        Returns:
            A :class:`DraftBatch` containing all generated drafts.
        """
        batch = DraftBatch()

        for msg in messages:
            try:
                body = await self._generator(msg, instruction)
            except Exception as exc:
                logger.warning(
                    "[BatchDraft] LLM generation failed for %s: %s",
                    msg.id,
                    exc,
                )
                body = await _default_draft_generator(msg, instruction)

            draft = Draft(
                channel=msg.channel,
                to=msg.sender,
                subject=f"Re: {msg.subject}" if not msg.subject.startswith("Re:") else msg.subject,
                body=body,
                in_reply_to=msg.id,
                thread_id=msg.thread_id,
                instruction=instruction,
            )
            batch.drafts.append(draft)

        return batch

    # ── review helpers ───────────────────────────────────────────

    @staticmethod
    def approve(batch: DraftBatch, draft_id: str) -> bool:
        """Approve a draft in the batch."""
        if any(d.id == draft_id for d in batch.drafts):
            batch.approve(draft_id)
            return True
        return False

    @staticmethod
    def skip(batch: DraftBatch, draft_id: str) -> bool:
        """Skip a draft in the batch."""
        if any(d.id == draft_id for d in batch.drafts):
            batch.skip(draft_id)
            return True
        return False

    @staticmethod
    def edit_draft(batch: DraftBatch, draft_id: str, **fields: Any) -> bool:
        """Edit a draft's fields (body, subject, to, …)."""
        for d in batch.drafts:
            if d.id == draft_id:
                for k, v in fields.items():
                    if hasattr(d, k):
                        object.__setattr__(d, k, v)
                return True
        return False

    @staticmethod
    def approve_all(batch: DraftBatch) -> int:
        """Approve every draft in the batch.  Returns count."""
        count = 0
        for d in batch.drafts:
            batch.approve(d.id)
            count += 1
        return count

    # ── sending ──────────────────────────────────────────────────

    async def send_approved(
        self, batch: DraftBatch
    ) -> list[SendResult]:
        """Send all approved drafts through the channel.

        Returns:
            List of :class:`SendResult` — one per approved draft.
        """
        results: list[SendResult] = []
        for draft in batch.get_approved_drafts():
            try:
                result = await self._channel.send(draft)
            except Exception as exc:
                logger.error(
                    "[BatchDraft] send failed for draft %s: %s",
                    draft.id,
                    exc,
                )
                result = SendResult(
                    ok=False,
                    channel=draft.channel,
                    error=str(exc),
                )
            results.append(result)
        return results

    # ── display ──────────────────────────────────────────────────

    @staticmethod
    def format_batch_display(batch: DraftBatch) -> str:
        """Format the batch for terminal / chat display (Turkish)."""
        if not batch.drafts:
            return "Taslak bulunamadı."

        lines = [f"📝 Batch Draft Modu — {batch.total} taslak:\n"]
        for i, d in enumerate(batch.drafts, 1):
            decision = batch.decisions.get(d.id)
            status = ""
            if decision == DraftDecision.APPROVE:
                status = " ✅"
            elif decision == DraftDecision.SKIP:
                status = " ❌"

            lines.append(
                f"{i}/{batch.total} — {d.to}{status}\n"
                f"   Konu: \"{d.subject}\"\n"
                f"   Taslak: \"{d.body[:120]}{'…' if len(d.body) > 120 else ''}\"\n"
            )

        approved = batch.approved_count
        pending = batch.pending_count
        lines.append(
            f"→ {approved} onaylı, {pending} bekliyor, "
            f"{batch.total - approved - pending} atlanan"
        )
        return "\n".join(lines)

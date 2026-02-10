---
title: "[Core] Otonom Gece Modu — Kendi Kendine Çalışan Agent"
labels: "type:feature, priority:P1, area:core, milestone:v2"
assignees: "miclaldogan"
issue_number: 808
---

## Hedef

"Bantz gece şunu yap" dendiğinde, Bantz'ın sabaha kadar kendi kendine çalışabilmesi. OpenClaw'daki "gece çalışan ajanlar" konseptini Bantz mimarisine taşımak.

## Arka Plan

Kullanıcı vizyonu: "OpenClaw'daki ajanlar gece şunu yap deyince sabaha kadar kendi kendilerine çalışabiliyorlar. Benim asistanım da güzelce kendi kendine çalışabilsin"

Mevcut durum: `automation/` modülünde PEV (Planner-Executor-Verifier) framework var ama:
- Uzun süreli otonom çalışma yok
- Background task queue yok
- Progress reporting yok
- Hata sonrası recovery policy basit

## Kapsam

### Dahil

- **Otonom görev kuyruğu**: Uzun süreli görevler sıraya alınıp arka planda çalışır
- **Progress tracking**: Her adımda ilerleme kaydı (log + notification)
- **Checkpoint + resume**: Hata sonrası kaldığı yerden devam
- **Resource aware**: GPU/API rate limit'e göre tempo ayarı
- **Sabah raporu**: Gece yapılanların özeti
- **İnsan müdahalesi**: Kritik karar noktalarında bekle, sabah sor
- **Görev tipleri**: Araştırma, toplu mail, doküman analizi, kod yazma (gelecek)

### Hariç

- Tam otonom karar verme (güvenlik sebebiyle insan onayı korunacak)
- Multi-agent koordinasyonu (ileri aşama)

## Teknik Tasarım

```python
# src/bantz/autonomous/engine.py

class AutonomousEngine:
    """Gece modu / uzun süreli otonom görev çalıştırıcı."""

    def __init__(self, brain, pev, memory, notification_bus):
        self.task_queue: PriorityQueue[AutonomousTask] = PriorityQueue()
        self.checkpoints: dict[str, Checkpoint] = {}

    async def submit_task(self, task: AutonomousTask):
        """Kullanıcı: 'gece şunu yap' → görev kuyruğa eklenir."""
        plan = await self.pev.planner.plan(task.description)
        task.plan = plan
        task.status = TaskStatus.QUEUED
        self.task_queue.put(task)

    async def run_overnight(self):
        """Daemon mode: sıradaki görevleri çalıştır."""
        while not self.task_queue.empty():
            task = self.task_queue.get()
            try:
                await self._execute_with_checkpoints(task)
            except HumanDecisionRequired as e:
                task.status = TaskStatus.WAITING_HUMAN
                self.pending_decisions.append(e.decision)
            except Exception as e:
                task.status = TaskStatus.FAILED
                await self._handle_failure(task, e)

    async def get_morning_report(self) -> str:
        """Sabah özeti: neler yapıldı, neler bekliyor."""
        ...

class AutonomousTask:
    id: str
    description: str
    plan: list[PlanStep]
    status: TaskStatus  # QUEUED | RUNNING | WAITING_HUMAN | DONE | FAILED
    checkpoints: list[Checkpoint]
    priority: int
    submitted_at: datetime
    deadline: Optional[datetime]

class Checkpoint:
    task_id: str
    step_index: int
    state: dict
    created_at: datetime
```

### Kullanım Örneği:

```
22:00 — Kullanıcı: "Bantz, gece şu 3 şeyi yap:
  1. Yapay zeka konferanslarını araştır, Mart ayında Türkiye'de ne var
  2. Son 1 haftanın AI haberlerini özetle
  3. Yarınki toplantı için gündem taslağı hazırla"

Bantz: "Anladım efendim. 3 görevi sıraya aldım:
  ✅ Yapay zeka konferansları araştırması
  ✅ Haftalık AI haber özeti
  ✅ Toplantı gündem taslağı
  Sabah sonuçları hazır olacak. İyi geceler!"

[Gece boyunca çalışır...]

07:00 — Sabah raporu:
  "Günaydın efendim! Gece 3 görevi tamamladım:
   ✅ 4 konferans buldum (detaylar aşağıda)
   ✅ Haftalık AI özeti hazır (12 önemli gelişme)
   ⚠️ Toplantı gündemi için bir kararınız gerekiyor:
      Bütçe konusu gündemde olsun mu?"
```

## Kabul Kriterleri

- [ ] `bantz --overnight` veya "gece şunu yap" komutu çalışıyor
- [ ] Görev kuyruğu çalışıyor (birden fazla görev sırayla)
- [ ] Checkpoint sistemi: hata sonrası kaldığı yerden devam
- [ ] Sabah raporu oluşturuluyor
- [ ] İnsan kararı gereken noktalarda duruyor (WAITING_HUMAN)
- [ ] Progress log'u tutuluyor (her adım kaydediliyor)
- [ ] Rate limiting farkındalığı (API sınırlarına uygun tempo)
- [ ] En az 2 görev tipi çalışıyor (araştırma + özet)
- [ ] Test yazıldı

## Bağımlılıklar

- Mevcut `automation/` PEV framework genişletilecek
- Issue #806 (Proaktif Zeka) — sabah raporu mekanizması
- Mevcut `scheduler/` modülü

## Tahmini Süre: 5-7 gün

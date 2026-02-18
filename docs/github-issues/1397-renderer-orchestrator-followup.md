# Issue Draft — #1397 Renderer ↔ Orchestrator Follow-up

## Summary
`bantz-overlay/src/renderer` ile orchestrator/daemon akışında kalan entegrasyon boşluklarını kapat.

## Context
- Overlay UI boot + panel akışı çalışıyor.
- Tool sonuçları Ingest/Graph katmanına aktarılıyor, ancak uçtan uca gözlem ve fallback senaryoları daha net hale getirilmeli.
- Amaç: renderer panel davranışı, daemon mesaj sözleşmesi ve startup command (`python3 -m bantz`) akışını tek bir “golden path”te doğrulamak.

## Scope
1. Daemon mesaj sözleşmesi (briefing_start/card/end, state, event) için açık contract testleri.
2. Overlay tarafında `news`, `calendar`, `mail`, `weather`, `system` kartlarının eksiksiz eşleşme doğrulaması.
3. `python3 -m bantz` başlatıldığında overlay bağlantısının (Unix socket) 30sn içinde kurulmasının health check’i.
4. Daemon yokken fallback panel verilerinin güvenli degrade davranışı.
5. Ingest/Graph metriklerinin observability loguna eklenmesi (turn başına cache-hit / link-count).

## Acceptance Criteria
- [ ] Overlay başlatıldığında bağlantı durumu `connecting -> connected` geçişi deterministik.
- [ ] Briefing kartlarında kategoriye göre panel yönlendirmesi %100 doğru.
- [ ] Daemon bağlantısı kesilince kullanıcıya tekil fallback mesajı gösterilir ve yeniden bağlanır.
- [ ] `python3 -m bantz` ile cold start senaryosu dokümante edilir.
- [ ] En az 1 integration test, 1 failure-mode test eklenir.

## Notes
- Bu issue, #1397 epik altında kapanış öncesi son entegrasyon checklist’i olarak kullanılabilir.

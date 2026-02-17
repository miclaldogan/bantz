/**
 * Bantz Overlay — Demo Mode Controller
 *
 * Populates all HUD panels with realistic mock data so the
 * overlay can be tested without a running daemon. Activated
 * automatically when no daemon connection is detected within 3s,
 * or manually via window.bantzDemo.start().
 *
 * @module demo-mode
 */

'use strict';

// ── Demo Data ─────────────────────────────────────────────────────

const DEMO_NEWS = [
  { title: 'Yapay zeka araştırmalarında yeni atılım', source: 'TRT Haber', summary: 'Türk bilim insanları, doğal dil işleme alanında çığır açan bir model geliştirdi.' },
  { title: 'Linux 7.0 çekirdeği duyuruldu', source: 'Phoronix', summary: 'Linus Torvalds yeni performans iyileştirmelerini paylaştı.' },
  { title: 'SpaceX Mars görevine hazırlanıyor', source: 'Space.com', summary: '2027 Mars misyonu için Starship test uçuşları başladı.' },
  { title: 'Küresel iklim zirvesi sonuçlandı', source: 'Reuters', summary: 'Karbon emisyonu hedefleri yeniden belirlendi.' },
  { title: 'Quantum bilgisayarlar yeni rekor kırdı', source: 'Nature', summary: 'Google 1000-qubit eşiğini geçen ilk çipi tanıttı.' },
  { title: 'Türkiye ekonomisi büyüme verilerini açıkladı', source: 'Bloomberg HT', summary: 'Son çeyrekte %4.2 büyüme kaydedildi.' },
  { title: 'Yeni nesil GPU mimarisi ortaya çıktı', source: 'Tom\'s Hardware', summary: 'NVIDIA Blackwell Ultra tanıtıldı, AI performansı 3x artış.' },
  { title: 'Open source LLM modelleri yaygınlaşıyor', source: 'Hacker News', summary: 'Mistral ve Llama 4 açık kaynak modellerle rekabet kızışıyor.' },
];

const DEMO_EVENTS = [
  { title: 'Takvim entegrasyonu bekleniyor', start: _todayAt(0, 0), end: _todayAt(23, 59), all_day: true },
];

const DEMO_TASKS = [
  { title: 'Google Calendar entegrasyonu', completed: false },
  { title: 'Overlay HUD test', completed: true },
  { title: 'Sistem entegrasyonu', completed: true },
  { title: 'Haber akışı entegrasyonu', completed: true },
];

const DEMO_WEATHER = {
  temperature: 7,
  condition: 'cloudy',
  humidity: 68,
  wind_speed: 12,
};

const DEMO_SYSTEM = {
  cpu: 34,
  ram: 62,
  disk: 41,
  uptime_seconds: 86400 + 3600 * 5 + 60 * 23, // 1 gün 5 saat 23 dk
};

const DEMO_SPEECH_TOKENS = [
  'Günaydın! ',
  'Bugün ',
  'hava ',
  'biraz ',
  'bulutlu, ',
  '7 derece. ',
  'Takviminde ',
  '5 etkinlik ',
  'var. ',
  'İlk olarak ',
  'saat 9\'da ',
  'standup, ',
  'sonra ',
  '10\'da ',
  'kod inceleme ',
  'var. ',
  'Öğleden ',
  'sonra ',
  'sprint ',
  'planlama ',
  've ',
  'AI okuma ',
  'grubu ',
  'bekliyor. ',
  'Haberlere ',
  'bakarsak, ',
  'yapay ',
  'zeka ',
  'araştırmalarında ',
  'yeni ',
  'ilginç ',
  'gelişmeler ',
  'var. ',
  'Sistem ',
  'durumun ',
  'stabil, ',
  'CPU %34, ',
  'RAM %62.',
];

const DEMO_REASONING_TOKENS = [
  'Kullanıcı ',
  'profili → ',
  'sabah ',
  'rutini, ',
  'haber + ',
  'takvim ',
  'brifing, ',
  'kısa tutulmalı ',
  '(30-40sn), ',
  'türkçe...',
];

// ── Helpers ───────────────────────────────────────────────────────

function _todayAt(h, m) {
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d.toISOString();
}

function _delay(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// ── Demo Mode Class ───────────────────────────────────────────────

class DemoMode {
  constructor() {
    this._running = false;
    this._timers = [];
    this._autoStartTimer = null;
  }

  /**
   * Start demo mode — populate all panels with mock data.
   */
  async start() {
    if (this._running) return;
    this._running = true;
    console.log('[DemoMode] ═══ STARTING DEMO MODE ═══');

    // 0. Force panels visible
    this._forceShowPanels();

    // 1. System status (instant)
    this._populateSystemStatus();

    // 2. Daily tasks (instant)
    this._populateDailyTasks();

    await _delay(300);

    // 3. News feed (staggered)
    await this._populateNewsFeed();

    await _delay(500);

    // 4. Reasoning chain (fast tokens)
    await this._showReasoning();

    await _delay(800);

    // 5. Speech (typewriter tokens)
    await this._showSpeech();

    // 6. Sphere state changes
    this._cycleSphereStates();

    console.log('[DemoMode] ═══ DEMO MODE ACTIVE ═══');
  }

  /**
   * Stop demo mode.
   */
  stop() {
    this._running = false;
    this._timers.forEach(t => clearTimeout(t));
    this._timers = [];
    console.log('[DemoMode] Stopped');
  }

  /**
   * Schedule auto-start if no daemon connects within timeout.
   * @param {number} timeoutMs — ms to wait for daemon (default 3000)
   */
  scheduleAutoStart(timeoutMs = 3000) {
    this._autoStartTimer = setTimeout(() => {
      // Check if a briefing already arrived (panels have data)
      const hasBriefingData = window.bantzNewsFeed &&
        window.bantzNewsFeed._articles && window.bantzNewsFeed._articles.length > 0;

      if (!hasBriefingData) {
        console.log('[DemoMode] No briefing data received — auto-starting demo');
        this.start();
      }
    }, timeoutMs);
  }

  /**
   * Cancel auto-start (called when daemon connects).
   */
  cancelAutoStart() {
    if (this._autoStartTimer) {
      clearTimeout(this._autoStartTimer);
      this._autoStartTimer = null;
    }
  }

  // ── Internal Population Methods ─────────────────────────────────

  _forceShowPanels() {
    // Directly show panels that are mounted but hidden
    const panels = [
      window.bantzNewsFeed,
      window.bantzDailyTasks,
      window.bantzSystemStatus,
      window.bantzClock,
    ];

    panels.forEach(panel => {
      if (panel && panel._panel) {
        panel._panel.show();
      } else if (panel && panel.show) {
        panel.show();
      }
    });

    // If layout engine exists, show all registered panels
    if (window.bantzLayout) {
      const ids = window.bantzLayout.getPanelIds();
      ids.forEach(id => window.bantzLayout.show(id));
    }

    // Play boot sequence if available
    if (window.bantzTransitions && !window.bantzTransitions._bootPlayed) {
      window.bantzTransitions.playBootSequence(
        {
          'daily-tasks': window.bantzDailyTasks,
          'news-feed': window.bantzNewsFeed,
          'system-status': window.bantzSystemStatus,
          'clock': window.bantzClock,
        },
        window.bantzSphere
      );
    }
  }

  _populateSystemStatus() {
    const ss = window.bantzSystemStatus;
    if (!ss) { console.warn('[DemoMode] SystemStatus not available'); return; }

    // Fetch REAL weather data
    if (window.overlayAPI && window.overlayAPI.getWeather) {
      window.overlayAPI.getWeather().then(weather => {
        if (weather) {
          ss.setWeather(weather);
          console.log(`[DemoMode] Real weather: ${weather.temperature}°C ${weather.condition} (${weather.location})`);
        } else {
          ss.setWeather(DEMO_WEATHER);
          console.log('[DemoMode] Weather API failed, using fallback');
        }
      }).catch(() => {
        ss.setWeather(DEMO_WEATHER);
      });
    } else {
      ss.setWeather(DEMO_WEATHER);
    }

    // Fetch REAL system metrics
    this._refreshSystemMetrics();

    // Set up periodic real metrics refresh (every 5s)
    const metricsInterval = setInterval(() => {
      if (!this._running) { clearInterval(metricsInterval); return; }
      this._refreshSystemMetrics();
    }, 5000);
    this._timers.push(metricsInterval);

    // Refresh weather hourly
    const weatherInterval = setInterval(() => {
      if (!this._running) { clearInterval(weatherInterval); return; }
      if (window.overlayAPI && window.overlayAPI.getWeather) {
        window.overlayAPI.getWeather().then(weather => {
          if (weather && window.bantzSystemStatus) {
            window.bantzSystemStatus.setWeather(weather);
          }
        }).catch(() => {});
      }
    }, 3600000); // 1 hour
    this._timers.push(weatherInterval);

    console.log('[DemoMode] System status populated (real data)');
  }

  _refreshSystemMetrics() {
    const ss = window.bantzSystemStatus;
    if (!ss) return;

    if (window.overlayAPI && window.overlayAPI.getSystemMetrics) {
      window.overlayAPI.getSystemMetrics().then(metrics => {
        if (metrics) {
          ss.setSystemMetrics(metrics);
        }
      }).catch(() => {});
    } else {
      ss.setSystemMetrics(DEMO_SYSTEM);
    }
  }

  _populateDailyTasks() {
    const dt = window.bantzDailyTasks;
    if (!dt) { console.warn('[DemoMode] DailyTasks not available'); return; }

    DEMO_EVENTS.forEach(e => dt.addEvent(e));
    DEMO_TASKS.forEach(t => dt.addTask(t));
    console.log('[DemoMode] Daily tasks populated');
  }

  async _populateNewsFeed() {
    const nf = window.bantzNewsFeed;
    if (!nf) { console.warn('[DemoMode] NewsFeed not available'); return; }

    // Try real RSS news first
    let articles = null;
    if (window.overlayAPI && window.overlayAPI.getNewsFeed) {
      try {
        articles = await window.overlayAPI.getNewsFeed();
        if (articles && articles.length > 0) {
          console.log(`[DemoMode] Got ${articles.length} real news articles`);
        } else {
          articles = null;
        }
      } catch {
        articles = null;
      }
    }

    // Fallback to demo news if real feed fails
    const newsToShow = articles || DEMO_NEWS;
    const isReal = articles !== null;

    for (const article of newsToShow) {
      nf.addArticle({
        title: article.title,
        source: article.source || '',
        summary: article.summary || '',
        link: article.link || '',
        id: `${isReal ? 'rss' : 'demo'}-${Math.random().toString(36).slice(2, 8)}`,
        ts: article.pubDate ? new Date(article.pubDate).getTime() : Date.now(),
      });
      await _delay(150);
    }

    // Highlight first article
    const allArticles = nf._articles;
    if (allArticles.length > 0) {
      nf.highlightArticle(allArticles[0].id);
    }

    // Set up periodic news refresh (every 5 minutes)
    if (isReal) {
      const newsInterval = setInterval(async () => {
        if (!this._running) { clearInterval(newsInterval); return; }
        try {
          const fresh = await window.overlayAPI.getNewsFeed();
          if (fresh && fresh.length > 0 && window.bantzNewsFeed) {
            // Add only new articles (check by title to avoid duplicates)
            const existing = new Set(window.bantzNewsFeed._articles.map(a => a.title));
            for (const a of fresh) {
              if (!existing.has(a.title)) {
                window.bantzNewsFeed.addArticle({
                  title: a.title,
                  source: a.source || '',
                  summary: a.summary || '',
                  link: a.link || '',
                  id: `rss-${Math.random().toString(36).slice(2, 8)}`,
                  ts: a.pubDate ? new Date(a.pubDate).getTime() : Date.now(),
                });
              }
            }
          }
        } catch {}
      }, 300000);
      this._timers.push(newsInterval);
    }

    console.log(`[DemoMode] News feed populated (${isReal ? 'REAL RSS' : 'demo fallback'})`);

    // Fetch OG images for top articles (in background)
    this._fetchArticleImages(newsToShow);
  }

  /**
   * Fetch Open Graph images for news articles and cache them.
   * Triggers popups during speech when images are available.
   */
  async _fetchArticleImages(articles) {
    if (!window.overlayAPI || !window.overlayAPI.getArticleImage) return;

    this._articleImages = [];
    const top = articles.slice(0, 4); // fetch images for top 4

    for (const article of top) {
      if (!this._running) break;
      if (!article.link) continue;
      try {
        const imageUrl = await window.overlayAPI.getArticleImage(article.link);
        if (imageUrl) {
          this._articleImages.push({
            image_url: imageUrl,
            title: article.title,
            source: article.source || '',
            url: article.link,
          });
          console.log(`[DemoMode] Got OG image for: ${article.title.slice(0, 40)}`);
        }
      } catch {}
    }
    console.log(`[DemoMode] Fetched ${this._articleImages.length} article images`);
  }

  /**
   * Show cached article image popups one by one.
   */
  async _showArticlePopups() {
    const popup = window.bantzNewsImagePopup;
    if (!popup) return;
    if (!this._articleImages || this._articleImages.length === 0) return;

    for (const img of this._articleImages) {
      if (!this._running) break;
      popup.show(img);
      await _delay(3000); // stagger popups
    }
  }

  async _showReasoning() {
    const rc = window.bantzReasoningChain;
    if (!rc) { console.warn('[DemoMode] ReasoningChain not available'); return; }

    rc.begin();
    for (const token of DEMO_REASONING_TOKENS) {
      if (!this._running) break;
      rc.addToken(token);
      await _delay(60);
    }
    // Keep reasoning visible during speech start
  }

  async _showSpeech() {
    const tw = window.bantzTypewriter;
    if (!tw) { console.warn('[DemoMode] Typewriter not available'); return; }

    // End reasoning when speech starts
    const rc = window.bantzReasoningChain;
    if (rc) {
      await _delay(300);
      rc.end();
    }

    // Build dynamic speech from real data
    const tokens = await this._buildSpeechTokens();

    tw.beginSpeech();

    for (const token of tokens) {
      if (!this._running) break;
      // Check for trigger tokens (non-string objects)
      if (token && typeof token === 'object' && token.__trigger === 'news-popups') {
        this._showArticlePopups(); // fire-and-forget, don't await
        continue;
      }
      tw.addToken(token);
      await _delay(50 + Math.random() * 30);
    }

    await _delay(1500);
    tw.endSpeech();

    console.log('[DemoMode] Speech complete');
  }

  /**
   * Build speech tokens from real system data when available.
   */
  async _buildSpeechTokens() {
    const parts = ['Günaydın! '];

    // Weather context
    try {
      if (window.overlayAPI && window.overlayAPI.getWeather) {
        const w = await window.overlayAPI.getWeather();
        if (w) {
          parts.push(`Bugün `, `${w.location || 'burada'} `, `${w.temperature}°C, `, `${w.condition}. `);
          if (w.humidity) parts.push(`Nem %${w.humidity}. `);
        }
      }
    } catch {}

    // System metrics context
    try {
      if (window.overlayAPI && window.overlayAPI.getSystemMetrics) {
        const m = await window.overlayAPI.getSystemMetrics();
        if (m) {
          parts.push('Sistem ', 'durumun ');
          if (m.cpu < 50) parts.push('stabil, ');
          else if (m.cpu < 80) parts.push('orta yükte, ');
          else parts.push('yüksek yükte, ');
          parts.push(`CPU %${m.cpu}, `, `RAM %${m.ram}. `);
        }
      }
    } catch {}

    // Calendar context
    const evtCount = (window.bantzDailyTasks && window.bantzDailyTasks._events)
      ? window.bantzDailyTasks._events.length : 0;
    if (evtCount > 0) {
      parts.push(`Takviminde `, `${evtCount} etkinlik `, `var. `);
    }

    // News context
    const newsCount = (window.bantzNewsFeed && window.bantzNewsFeed._articles)
      ? window.bantzNewsFeed._articles.length : 0;
    if (newsCount > 0) {
      parts.push('Haberlere ', 'bakarsak, ');
      const firstArticle = window.bantzNewsFeed._articles[0];
      if (firstArticle) {
        parts.push(`"${firstArticle.title.slice(0, 40)}" `, 'dikkat çekiyor. ');
      }
      // Mark where news popups should trigger
      parts.push({ __trigger: 'news-popups' });
    }

    // Fallback if nothing was collected
    if (parts.length <= 1) {
      return DEMO_SPEECH_TOKENS;
    }

    return parts;
  }

  _cycleSphereStates() {
    const sa = window.bantzStateAnimator;
    if (!sa) { console.warn('[DemoMode] SphereStateAnimator not available'); return; }

    const states = ['idle', 'listening', 'thinking', 'speaking', 'idle'];
    let i = 0;

    const cycleNext = () => {
      if (!this._running || i >= states.length) return;
      sa.setState(states[i]);

      // Trigger glitch effects on transitions
      const ge = window.bantzGlitchEffects;
      if (ge) {
        if (states[i] === 'thinking') ge.triggerChromatic('intense');
        else if (states[i] === 'listening') ge.triggerChromatic('normal');
        else if (states[i] === 'speaking') ge.triggerChromatic('normal');
      }

      i++;
      const timer = setTimeout(cycleNext, 4000);
      this._timers.push(timer);
    };

    // Start after speech begins
    const startTimer = setTimeout(cycleNext, 2000);
    this._timers.push(startTimer);

    console.log('[DemoMode] Sphere state cycling started');
  }
}

// ── Expose globally ───────────────────────────────────────────────
window.BantzDemoMode = DemoMode;

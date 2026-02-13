/**
 * Bantz Browser Extension v2 - Page Extractor
 * Extract structured content from web pages
 */

class PageExtractor {
  constructor() {
    this.lastExtractionTime = 0;
  }

  // ========================================================================
  // Content Extraction
  // ========================================================================

  /**
   * Extract all page content
   */
  extract(options = {}) {
    const {
      maxTextLength = 10000,
      maxLinks = 100,
      maxImages = 50,
      includeMetadata = true,
    } = options;

    const startTime = performance.now();

    const content = {
      // Basic info
      title: document.title,
      url: location.href,
      hostname: location.hostname,

      // Text content
      text: this.extractMainText(maxTextLength),

      // Structure
      headings: this.extractHeadings(),
      links: this.extractLinks(maxLinks),
      images: this.extractImages(maxImages),

      // Metadata
      meta: includeMetadata ? this.extractMetadata() : null,

      // Page state
      readyState: document.readyState,
      hasVideo: document.querySelectorAll('video').length > 0,
      hasAudio: document.querySelectorAll('audio').length > 0,
      hasIframes: document.querySelectorAll('iframe').length > 0,

      // Language
      language: document.documentElement.lang || this.detectLanguage(),

      // Extraction time
      extractionTime: 0,
    };

    content.extractionTime = performance.now() - startTime;
    this.lastExtractionTime = content.extractionTime;

    return content;
  }

  /**
   * Extract main text content
   */
  extractMainText(maxLength = 10000) {
    // Try to find main content area
    const mainSelectors = [
      'main',
      'article',
      '[role="main"]',
      '.main-content',
      '#main-content',
      '.post-content',
      '.article-content',
      '.entry-content',
    ];

    let mainElement = null;
    for (const selector of mainSelectors) {
      mainElement = document.querySelector(selector);
      if (mainElement) break;
    }

    // Fall back to body
    const targetElement = mainElement || document.body;

    // Clone and clean
    const clone = targetElement.cloneNode(true);

    // Remove non-content elements
    const removeSelectors = [
      'script', 'style', 'noscript', 'iframe',
      'nav', 'header', 'footer', 'aside',
      '.sidebar', '.navigation', '.menu', '.ad', '.advertisement',
      '.comments', '.social-share', '.related-posts',
    ];

    removeSelectors.forEach(sel => {
      clone.querySelectorAll(sel).forEach(el => el.remove());
    });

    // Get text
    let text = clone.innerText || clone.textContent || '';

    // Clean up whitespace
    text = text
      .replace(/\s+/g, ' ')
      .replace(/\n\s*\n/g, '\n\n')
      .trim();

    return text.slice(0, maxLength);
  }

  /**
   * Extract headings hierarchy
   */
  extractHeadings() {
    const headings = [];
    const headingElements = document.querySelectorAll('h1, h2, h3, h4, h5, h6');

    headingElements.forEach(h => {
      const text = h.textContent.trim();
      if (!text) return;

      headings.push({
        level: parseInt(h.tagName[1]),
        text: text.slice(0, 200),
        id: h.id || null,
      });
    });

    return headings;
  }

  /**
   * Extract links
   */
  extractLinks(maxLinks = 100) {
    const links = [];
    const seen = new Set();
    const linkElements = document.querySelectorAll('a[href]');

    for (const a of linkElements) {
      if (links.length >= maxLinks) break;

      const href = a.href;
      // Security Alert #8: Check for data: and vbscript: schemes too
      if (!href || href.startsWith('javascript:') || href.startsWith('data:') || 
          href.startsWith('vbscript:') || href === '#') continue;
      if (seen.has(href)) continue;

      const text = a.textContent.trim();
      if (!text) continue;

      seen.add(href);
      links.push({
        text: text.slice(0, 100),
        href: href,
        isExternal: !href.includes(location.hostname),
        isVisible: this.isVisible(a),
      });
    }

    return links;
  }

  /**
   * Extract images
   */
  extractImages(maxImages = 50) {
    const images = [];
    const imgElements = document.querySelectorAll('img[src]');

    for (const img of imgElements) {
      if (images.length >= maxImages) break;

      const src = img.src;
      if (!src || src.startsWith('data:')) continue;

      // Skip tiny images (likely icons)
      if (img.naturalWidth < 50 || img.naturalHeight < 50) continue;

      images.push({
        src: src,
        alt: img.alt || null,
        width: img.naturalWidth,
        height: img.naturalHeight,
        isVisible: this.isVisible(img),
      });
    }

    return images;
  }

  /**
   * Extract page metadata
   */
  extractMetadata() {
    const meta = {
      description: null,
      keywords: null,
      author: null,
      ogTitle: null,
      ogDescription: null,
      ogImage: null,
      ogType: null,
      twitterCard: null,
      canonical: null,
      favicon: null,
    };

    // Standard meta tags
    const descMeta = document.querySelector('meta[name="description"]');
    if (descMeta) meta.description = descMeta.content;

    const keywordsMeta = document.querySelector('meta[name="keywords"]');
    if (keywordsMeta) meta.keywords = keywordsMeta.content;

    const authorMeta = document.querySelector('meta[name="author"]');
    if (authorMeta) meta.author = authorMeta.content;

    // Open Graph
    const ogTitle = document.querySelector('meta[property="og:title"]');
    if (ogTitle) meta.ogTitle = ogTitle.content;

    const ogDesc = document.querySelector('meta[property="og:description"]');
    if (ogDesc) meta.ogDescription = ogDesc.content;

    const ogImage = document.querySelector('meta[property="og:image"]');
    if (ogImage) meta.ogImage = ogImage.content;

    const ogType = document.querySelector('meta[property="og:type"]');
    if (ogType) meta.ogType = ogType.content;

    // Twitter Card
    const twitterCard = document.querySelector('meta[name="twitter:card"]');
    if (twitterCard) meta.twitterCard = twitterCard.content;

    // Canonical URL
    const canonical = document.querySelector('link[rel="canonical"]');
    if (canonical) meta.canonical = canonical.href;

    // Favicon
    const favicon = document.querySelector('link[rel="icon"], link[rel="shortcut icon"]');
    if (favicon) meta.favicon = favicon.href;

    return meta;
  }

  // ========================================================================
  // Specialized Extraction
  // ========================================================================

  /**
   * Extract video information
   */
  extractVideos() {
    const videos = [];

    // HTML5 videos
    document.querySelectorAll('video').forEach(video => {
      videos.push({
        type: 'html5',
        src: video.src || video.querySelector('source')?.src,
        duration: video.duration || null,
        paused: video.paused,
        currentTime: video.currentTime,
        muted: video.muted,
        volume: video.volume,
        isVisible: this.isVisible(video),
      });
    });

    // YouTube embeds
    document.querySelectorAll('iframe[src*="youtube.com"], iframe[src*="youtu.be"]').forEach(iframe => {
      videos.push({
        type: 'youtube',
        src: iframe.src,
        isVisible: this.isVisible(iframe),
      });
    });

    // Vimeo embeds
    document.querySelectorAll('iframe[src*="vimeo.com"]').forEach(iframe => {
      videos.push({
        type: 'vimeo',
        src: iframe.src,
        isVisible: this.isVisible(iframe),
      });
    });

    return videos;
  }

  /**
   * Extract article content (for news/blog sites)
   */
  extractArticle() {
    const article = {
      title: null,
      author: null,
      date: null,
      content: null,
      images: [],
    };

    // Title
    article.title = document.querySelector('h1')?.textContent.trim() ||
                   document.querySelector('article h2')?.textContent.trim() ||
                   document.title;

    // Author
    const authorSelectors = [
      '[rel="author"]',
      '.author',
      '.byline',
      '[itemprop="author"]',
    ];
    for (const sel of authorSelectors) {
      const el = document.querySelector(sel);
      if (el) {
        article.author = el.textContent.trim();
        break;
      }
    }

    // Date
    const dateSelectors = [
      'time[datetime]',
      '[itemprop="datePublished"]',
      '.date',
      '.published',
    ];
    for (const sel of dateSelectors) {
      const el = document.querySelector(sel);
      if (el) {
        article.date = el.getAttribute('datetime') || el.textContent.trim();
        break;
      }
    }

    // Content
    const contentEl = document.querySelector('article') ||
                     document.querySelector('.post-content') ||
                     document.querySelector('.article-content');
    if (contentEl) {
      article.content = contentEl.innerText.slice(0, 20000);
      article.images = Array.from(contentEl.querySelectorAll('img')).map(img => ({
        src: img.src,
        alt: img.alt,
      })).slice(0, 20);
    }

    return article;
  }

  /**
   * Extract product information (for e-commerce)
   */
  extractProduct() {
    const product = {
      name: null,
      price: null,
      currency: null,
      description: null,
      images: [],
      rating: null,
      availability: null,
    };

    // Schema.org product
    const productSchema = document.querySelector('[itemtype*="schema.org/Product"]');
    if (productSchema) {
      product.name = productSchema.querySelector('[itemprop="name"]')?.textContent.trim();
      product.description = productSchema.querySelector('[itemprop="description"]')?.textContent.trim();
      
      const priceEl = productSchema.querySelector('[itemprop="price"]');
      if (priceEl) {
        product.price = priceEl.content || priceEl.textContent.trim();
      }

      const currencyEl = productSchema.querySelector('[itemprop="priceCurrency"]');
      if (currencyEl) {
        product.currency = currencyEl.content;
      }
    }

    // JSON-LD product data
    const jsonLd = document.querySelector('script[type="application/ld+json"]');
    if (jsonLd) {
      try {
        const data = JSON.parse(jsonLd.textContent);
        if (data['@type'] === 'Product' || data.product) {
          const p = data.product || data;
          product.name = product.name || p.name;
          product.description = product.description || p.description;
          if (p.offers) {
            product.price = product.price || p.offers.price;
            product.currency = product.currency || p.offers.priceCurrency;
            product.availability = p.offers.availability;
          }
        }
      } catch (e) {
        // Invalid JSON-LD
      }
    }

    // Common price patterns
    if (!product.price) {
      const pricePatterns = [
        '.price', '.product-price', '.current-price',
        '[data-price]', '#price', '.offer-price',
      ];
      for (const sel of pricePatterns) {
        const el = document.querySelector(sel);
        if (el) {
          product.price = el.textContent.trim();
          break;
        }
      }
    }

    // Product images
    const imageSelectors = [
      '.product-image img',
      '.gallery img',
      '[itemprop="image"]',
    ];
    for (const sel of imageSelectors) {
      const imgs = document.querySelectorAll(sel);
      if (imgs.length > 0) {
        product.images = Array.from(imgs).map(img => img.src).slice(0, 10);
        break;
      }
    }

    return product;
  }

  /**
   * Extract search results
   */
  extractSearchResults() {
    const results = [];
    const hostname = location.hostname;

    // Google
    if (hostname.includes('google.')) {
      document.querySelectorAll('.g').forEach(el => {
        const link = el.querySelector('a');
        const title = el.querySelector('h3');
        const snippet = el.querySelector('.VwiC3b');
        
        if (link && title) {
          results.push({
            title: title.textContent,
            url: link.href,
            snippet: snippet?.textContent || '',
          });
        }
      });
    }

    // Bing
    else if (hostname.includes('bing.')) {
      document.querySelectorAll('.b_algo').forEach(el => {
        const link = el.querySelector('a');
        const snippet = el.querySelector('.b_caption p');
        
        if (link) {
          results.push({
            title: link.textContent,
            url: link.href,
            snippet: snippet?.textContent || '',
          });
        }
      });
    }

    // DuckDuckGo
    else if (hostname.includes('duckduckgo.')) {
      document.querySelectorAll('.result').forEach(el => {
        const link = el.querySelector('a.result__a');
        const snippet = el.querySelector('.result__snippet');
        
        if (link) {
          results.push({
            title: link.textContent,
            url: link.href,
            snippet: snippet?.textContent || '',
          });
        }
      });
    }

    return results;
  }

  // ========================================================================
  // Utility Methods
  // ========================================================================

  /**
   * Check if element is visible
   */
  isVisible(el) {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  /**
   * Detect page language
   */
  detectLanguage() {
    // Check common Turkish words
    const text = document.body.innerText.toLowerCase();
    const turkishWords = ['ve', 'için', 'bir', 'ile', 'olan', 'değil', 'gibi'];
    const englishWords = ['the', 'and', 'for', 'with', 'this', 'that', 'from'];

    let turkishCount = 0;
    let englishCount = 0;

    turkishWords.forEach(word => {
      const regex = new RegExp(`\\b${word}\\b`, 'g');
      turkishCount += (text.match(regex) || []).length;
    });

    englishWords.forEach(word => {
      const regex = new RegExp(`\\b${word}\\b`, 'g');
      englishCount += (text.match(regex) || []).length;
    });

    if (turkishCount > englishCount * 2) return 'tr';
    if (englishCount > turkishCount * 2) return 'en';

    return 'unknown';
  }

  /**
   * Get page summary
   */
  getSummary() {
    const meta = this.extractMetadata();

    return {
      title: document.title,
      description: meta.description || meta.ogDescription || this.extractMainText(200),
      url: location.href,
      language: document.documentElement.lang || this.detectLanguage(),
      image: meta.ogImage,
      type: meta.ogType || 'website',
    };
  }

  /**
   * Quick page info for voice responses
   */
  getQuickInfo() {
    return {
      title: document.title,
      url: location.href,
      linkCount: document.querySelectorAll('a[href]').length,
      imageCount: document.querySelectorAll('img').length,
      formCount: document.querySelectorAll('form').length,
      videoCount: document.querySelectorAll('video, iframe[src*="youtube"], iframe[src*="vimeo"]').length,
    };
  }
}

// Export for use in content.js
if (typeof window !== 'undefined') {
  window.BantzPageExtractor = PageExtractor;
}

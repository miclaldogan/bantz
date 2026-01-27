/**
 * Bantz Browser Extension v2 - Form Detector
 * Intelligent form detection for login, search, contact, checkout
 */

class FormDetector {
  constructor() {
    this.forms = [];
    this.lastDetectionTime = 0;
  }

  // ========================================================================
  // Form Type Detection
  // ========================================================================

  /**
   * Detect all forms on page
   */
  detect() {
    this.forms = [];
    const startTime = performance.now();

    // Find all forms
    const formElements = document.querySelectorAll('form');
    formElements.forEach((form, index) => {
      const formInfo = this.analyzeForm(form, index);
      if (formInfo) {
        this.forms.push(formInfo);
      }
    });

    // Also detect implicit forms (inputs not in form tags)
    this.detectImplicitForms();

    this.lastDetectionTime = performance.now() - startTime;

    return {
      forms: this.forms,
      count: this.forms.length,
      detectionTime: this.lastDetectionTime,
    };
  }

  /**
   * Analyze a form element
   */
  analyzeForm(form, index) {
    const fields = this.extractFields(form);
    if (fields.length === 0) return null;

    const formType = this.classifyForm(form, fields);
    const rect = form.getBoundingClientRect();

    return {
      index: index,
      type: formType,
      action: form.action || null,
      method: form.method || 'get',
      name: form.name || form.id || null,
      
      rect: {
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },

      fields: fields,
      submitButton: this.findSubmitButton(form),
      
      // Hints for form handling
      hints: this.getFormHints(formType, fields),
    };
  }

  /**
   * Extract all input fields from form
   */
  extractFields(form) {
    const fields = [];
    const inputs = form.querySelectorAll('input, textarea, select');

    inputs.forEach(input => {
      if (input.type === 'hidden') return;
      if (!this.isFieldVisible(input)) return;

      fields.push(this.extractFieldInfo(input));
    });

    return fields;
  }

  /**
   * Extract info about a single field
   */
  extractFieldInfo(input) {
    const rect = input.getBoundingClientRect();
    const label = this.findLabel(input);

    return {
      tag: input.tagName.toLowerCase(),
      type: input.type || 'text',
      name: input.name || null,
      id: input.id || null,
      placeholder: input.placeholder || null,
      label: label,
      value: input.value || '',
      
      // Field classification
      fieldType: this.classifyField(input, label),
      
      required: input.required || input.getAttribute('aria-required') === 'true',
      disabled: input.disabled,
      readonly: input.readOnly,
      
      rect: {
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },

      // For select elements
      options: input.tagName === 'SELECT' ? this.getSelectOptions(input) : null,

      // Selector for interaction
      selector: this.generateFieldSelector(input),
    };
  }

  /**
   * Classify field purpose
   */
  classifyField(input, label) {
    const type = input.type || 'text';
    const name = (input.name || '').toLowerCase();
    const id = (input.id || '').toLowerCase();
    const placeholder = (input.placeholder || '').toLowerCase();
    const labelText = (label || '').toLowerCase();
    const autocomplete = input.autocomplete || '';

    // Password field
    if (type === 'password') return 'password';

    // Email field
    if (type === 'email' || autocomplete === 'email' ||
        /email|e-?mail/i.test(name + id + placeholder + labelText)) {
      return 'email';
    }

    // Username field
    if (autocomplete === 'username' ||
        /user|kullan|login|giriş|hesap/i.test(name + id + placeholder + labelText)) {
      return 'username';
    }

    // Phone field
    if (type === 'tel' || autocomplete === 'tel' ||
        /phone|telefon|tel|gsm|cep/i.test(name + id + placeholder + labelText)) {
      return 'phone';
    }

    // Name fields
    if (autocomplete.includes('name') ||
        /^(ad|soyad|isim|name|first|last)$/i.test(name) ||
        /(adınız|soyadınız|first\s*name|last\s*name)/i.test(labelText)) {
      if (/last|soyad|surname/i.test(name + id + labelText)) return 'lastName';
      if (/first|^ad$|isim/i.test(name + id + labelText)) return 'firstName';
      return 'name';
    }

    // Search field
    if (type === 'search' ||
        /search|ara|arat|query|q\b|sorgu/i.test(name + id + placeholder)) {
      return 'search';
    }

    // Address fields
    if (/address|adres|street|sokak|cadde/i.test(name + id + placeholder + labelText)) {
      return 'address';
    }

    // City
    if (/city|şehir|il\b/i.test(name + id + labelText)) {
      return 'city';
    }

    // Postal code
    if (/zip|postal|posta\s*kodu/i.test(name + id + labelText)) {
      return 'postalCode';
    }

    // Credit card
    if (/card|kart|cc|credit/i.test(name + id)) {
      if (/number|numara|no/i.test(name + id)) return 'cardNumber';
      if (/cvv|cvc|güvenlik/i.test(name + id)) return 'cardCvv';
      if (/expir|son kullanma|ay|yıl/i.test(name + id)) return 'cardExpiry';
      return 'card';
    }

    // Message/comment
    if (input.tagName === 'TEXTAREA' ||
        /message|mesaj|comment|yorum|açıklama|not/i.test(name + id + placeholder)) {
      return 'message';
    }

    // Subject
    if (/subject|konu|başlık/i.test(name + id + labelText)) {
      return 'subject';
    }

    return 'text';
  }

  /**
   * Classify form type
   */
  classifyForm(form, fields) {
    const fieldTypes = fields.map(f => f.fieldType);
    const hasPassword = fieldTypes.includes('password');
    const hasEmail = fieldTypes.includes('email');
    const hasUsername = fieldTypes.includes('username');
    const hasSearch = fieldTypes.includes('search');
    const hasPhone = fieldTypes.includes('phone');
    const hasMessage = fieldTypes.includes('message');
    const hasName = fieldTypes.some(t => t.includes('name') || t === 'name');
    const hasCard = fieldTypes.some(t => t.includes('card'));
    const hasAddress = fieldTypes.includes('address');

    // Login form
    if (hasPassword && (hasEmail || hasUsername) && fields.length <= 4) {
      return 'login';
    }

    // Registration form
    if (hasPassword && hasEmail && fields.length > 3) {
      return 'registration';
    }

    // Password reset
    if (hasPassword && fields.length === 1) {
      return 'password_reset';
    }

    // Search form
    if (hasSearch || (fields.length === 1 && fields[0].type === 'text')) {
      // Check if it looks like a search
      const action = (form.action || '').toLowerCase();
      const id = (form.id || '').toLowerCase();
      if (/search|ara|query/i.test(action + id)) {
        return 'search';
      }
      // Single text input with button is likely search
      if (fields.length === 1) {
        return 'search';
      }
    }

    // Contact form
    if (hasMessage && (hasEmail || hasPhone || hasName)) {
      return 'contact';
    }

    // Checkout form
    if (hasCard || (hasAddress && hasPhone)) {
      return 'checkout';
    }

    // Newsletter/subscription
    if (hasEmail && fields.length <= 2 && !hasPassword) {
      return 'newsletter';
    }

    // Profile form
    if (hasName && (hasEmail || hasPhone) && !hasPassword && !hasMessage) {
      return 'profile';
    }

    return 'unknown';
  }

  // ========================================================================
  // Helper Methods
  // ========================================================================

  /**
   * Find label for input
   */
  findLabel(input) {
    // Explicit label
    if (input.id) {
      const label = document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      if (label) return label.textContent.trim();
    }

    // Implicit label (input inside label)
    const parentLabel = input.closest('label');
    if (parentLabel) {
      // Get text without input value
      const clone = parentLabel.cloneNode(true);
      clone.querySelectorAll('input, select, textarea').forEach(el => el.remove());
      return clone.textContent.trim();
    }

    // aria-label
    const ariaLabel = input.getAttribute('aria-label');
    if (ariaLabel) return ariaLabel;

    // aria-labelledby
    const ariaLabelledBy = input.getAttribute('aria-labelledby');
    if (ariaLabelledBy) {
      const labelEl = document.getElementById(ariaLabelledBy);
      if (labelEl) return labelEl.textContent.trim();
    }

    // Previous sibling text
    let prev = input.previousElementSibling;
    if (prev && prev.tagName === 'LABEL') {
      return prev.textContent.trim();
    }

    return null;
  }

  /**
   * Find submit button for form
   */
  findSubmitButton(form) {
    // Explicit submit button
    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (submitBtn) {
      return this.getButtonInfo(submitBtn);
    }

    // Any button (often the submit)
    const buttons = form.querySelectorAll('button:not([type="reset"]):not([type="button"])');
    for (const btn of buttons) {
      if (this.isFieldVisible(btn)) {
        return this.getButtonInfo(btn);
      }
    }

    // Button with submit-like text
    const allButtons = form.querySelectorAll('button, input[type="button"], [role="button"]');
    for (const btn of allButtons) {
      const text = (btn.textContent || btn.value || '').toLowerCase();
      if (/submit|gönder|kaydet|giriş|ara|search|login|sign|register/i.test(text)) {
        return this.getButtonInfo(btn);
      }
    }

    return null;
  }

  /**
   * Get button info
   */
  getButtonInfo(btn) {
    const rect = btn.getBoundingClientRect();
    return {
      text: btn.textContent || btn.value || '',
      type: btn.type || 'button',
      selector: this.generateFieldSelector(btn),
      rect: {
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
    };
  }

  /**
   * Get options from select element
   */
  getSelectOptions(select) {
    const options = [];
    select.querySelectorAll('option').forEach(opt => {
      options.push({
        value: opt.value,
        text: opt.textContent.trim(),
        selected: opt.selected,
      });
    });
    return options;
  }

  /**
   * Check if field is visible
   */
  isFieldVisible(el) {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  /**
   * Generate selector for field
   */
  generateFieldSelector(el) {
    if (el.id) {
      return `#${CSS.escape(el.id)}`;
    }
    if (el.name) {
      const tag = el.tagName.toLowerCase();
      return `${tag}[name="${CSS.escape(el.name)}"]`;
    }
    // Fall back to type + position
    const tag = el.tagName.toLowerCase();
    const type = el.type;
    if (type) {
      return `${tag}[type="${type}"]`;
    }
    return tag;
  }

  /**
   * Detect implicit forms (inputs not in form tags)
   */
  detectImplicitForms() {
    // Find password fields not in forms
    const orphanPasswords = document.querySelectorAll('input[type="password"]');
    
    for (const pw of orphanPasswords) {
      if (pw.closest('form')) continue;

      // Look for nearby inputs
      const container = pw.closest('div, section, article, main') || document.body;
      const nearbyInputs = container.querySelectorAll('input:not([type="hidden"])');
      
      if (nearbyInputs.length > 1) {
        const fields = [];
        nearbyInputs.forEach(input => {
          if (this.isFieldVisible(input)) {
            fields.push(this.extractFieldInfo(input));
          }
        });

        if (fields.length > 0) {
          this.forms.push({
            index: this.forms.length,
            type: 'login',
            implicit: true,
            action: null,
            method: null,
            name: null,
            fields: fields,
            submitButton: this.findNearbyButton(container),
            hints: this.getFormHints('login', fields),
          });
        }
      }
    }

    // Find search boxes not in forms
    const orphanSearch = document.querySelectorAll(
      'input[type="search"], input[name*="search"], input[placeholder*="Search"], input[placeholder*="Ara"]'
    );

    for (const search of orphanSearch) {
      if (search.closest('form')) continue;
      if (!this.isFieldVisible(search)) continue;

      this.forms.push({
        index: this.forms.length,
        type: 'search',
        implicit: true,
        action: null,
        method: null,
        name: null,
        fields: [this.extractFieldInfo(search)],
        submitButton: this.findNearbyButton(search.parentElement),
        hints: this.getFormHints('search', []),
      });
    }
  }

  /**
   * Find nearby button for implicit forms
   */
  findNearbyButton(container) {
    if (!container) return null;

    const buttons = container.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]');
    for (const btn of buttons) {
      if (this.isFieldVisible(btn)) {
        return this.getButtonInfo(btn);
      }
    }
    return null;
  }

  /**
   * Get form handling hints
   */
  getFormHints(formType, fields) {
    const hints = {
      type: formType,
      fields: {},
    };

    switch (formType) {
      case 'login':
        hints.usernameField = fields.find(f => 
          f.fieldType === 'username' || f.fieldType === 'email'
        )?.selector;
        hints.passwordField = fields.find(f => 
          f.fieldType === 'password'
        )?.selector;
        hints.description = 'Giriş formu - kullanıcı adı ve şifre gerekli';
        break;

      case 'search':
        hints.searchField = fields.find(f => 
          f.fieldType === 'search' || f.type === 'text'
        )?.selector;
        hints.description = 'Arama formu - sorgu girin ve gönderin';
        break;

      case 'contact':
        hints.emailField = fields.find(f => f.fieldType === 'email')?.selector;
        hints.messageField = fields.find(f => f.fieldType === 'message')?.selector;
        hints.description = 'İletişim formu - mesaj göndermek için doldurun';
        break;

      case 'registration':
        hints.description = 'Kayıt formu - yeni hesap oluşturmak için doldurun';
        break;

      case 'newsletter':
        hints.emailField = fields.find(f => f.fieldType === 'email')?.selector;
        hints.description = 'Bülten formu - e-posta ile abone olun';
        break;

      case 'checkout':
        hints.description = 'Ödeme formu - kart bilgileri gerekli';
        break;

      default:
        hints.description = 'Bilinmeyen form tipi';
    }

    return hints;
  }

  // ========================================================================
  // Specific Form Detection
  // ========================================================================

  /**
   * Detect login form specifically
   */
  detectLoginForm() {
    const detected = this.detect();
    return detected.forms.find(f => f.type === 'login') || null;
  }

  /**
   * Detect search form specifically
   */
  detectSearchForm() {
    const detected = this.detect();
    return detected.forms.find(f => f.type === 'search') || null;
  }

  /**
   * Detect contact form specifically
   */
  detectContactForm() {
    const detected = this.detect();
    return detected.forms.find(f => f.type === 'contact') || null;
  }
}

// Export for use in content.js
if (typeof window !== 'undefined') {
  window.BantzFormDetector = FormDetector;
}

/**
 * Issue Observatory — main client-side script.
 *
 * Loaded in <head> (no defer) so that HTMX event listeners are registered
 * before the DOM is processed and Alpine.js components are defined before
 * Alpine boots (Alpine loads with defer, so it initialises after this script).
 *
 * Sections:
 *   1. HTMX global 401 handler
 *   2. HTMX HX-Redirect response header handler
 *   3. Alpine.js component definitions (registered before alpine:init fires)
 */

// ---------------------------------------------------------------------------
// 0. Alpine.js ↔ HTMX bridge
//    When hx-boost (or any HTMX swap) replaces page content, Alpine.js needs
//    to initialise new x-data components in the swapped DOM.  Without this,
//    @click handlers, x-ref, x-show etc. are dead after boost navigation.
// ---------------------------------------------------------------------------

document.addEventListener('htmx:load', function (evt) {
  if (window.Alpine) {
    window.Alpine.initTree(evt.detail.elt);
  }
});

// ---------------------------------------------------------------------------
// 1. HTMX global 401 handler
//    Intercept 401 responses BEFORE HTMX tries to swap error content into the
//    page. Saves the current path for post-login redirect and navigates to the
//    login page. Uses a flag to prevent multiple redirects from concurrent
//    polling triggers.
//
//    NOTE: listeners are on `document` (not document.body) because this script
//    runs in <head> before <body> exists.
// ---------------------------------------------------------------------------

(function () {
  var redirecting = false;

  function handleUnauthorized() {
    if (redirecting) return;
    redirecting = true;
    sessionStorage.setItem('redirect_after_login', window.location.pathname);
    window.location.href = '/auth/login?session_expired=1';
  }

  // Primary: intercept before swap so HTMX never replaces page content with
  // the 401 JSON body.
  document.addEventListener('htmx:beforeSwap', function (evt) {
    if (evt.detail.xhr.status === 401) {
      evt.detail.shouldSwap = false;
      handleUnauthorized();
    }
  });

  // Backup: catch any 401 that slips past beforeSwap.
  document.addEventListener('htmx:responseError', function (evt) {
    if (evt.detail.xhr.status === 401) {
      handleUnauthorized();
    }
  });
})();

// ---------------------------------------------------------------------------
// 1b. Strip empty query parameters from HTMX form submissions
//     When HTMX serializes a form, <select> elements with <option value="">
//     send empty strings. FastAPI rejects empty strings for UUID parameters
//     with HTTP 422. Strip empty values so they are treated as absent (None).
// ---------------------------------------------------------------------------

document.addEventListener('htmx:configRequest', function (evt) {
  var params = evt.detail.parameters;
  if (params && typeof params === 'object') {
    Object.keys(params).forEach(function (key) {
      if (params[key] === '') {
        delete params[key];
      }
    });
  }
});

// ---------------------------------------------------------------------------
// 2. HTMX HX-Redirect response header handler
//    HTMX 2 does not follow the HX-Redirect response header automatically
//    for non-boosted requests. We handle it here for all HTMX requests so
//    that the launcher POST (hx-post="/collections/") can redirect the browser
//    to the new run's detail page on success.
// ---------------------------------------------------------------------------

document.addEventListener('htmx:afterRequest', function (evt) {
  var redirect = evt.detail.xhr.getResponseHeader('HX-Redirect');
  if (redirect) {
    window.location.href = redirect;
  }
});

// ---------------------------------------------------------------------------
// 3. Alpine.js component definitions
//    Alpine is loaded with `defer` and calls `alpine:init` before booting.
//    We register all components here so they are available globally.
// ---------------------------------------------------------------------------

document.addEventListener('alpine:init', () => {

  /**
   * collectionLauncher — collection run launcher form.
   *
   * Defined here as a fallback; the launcher template also defines it inline
   * so it can receive the `availableCredits` server value. The inline version
   * takes precedence for that page. This global definition is a safety net.
   *
   * Actual implementation lives in collections/launcher.html <script> block
   * because it needs the server-rendered `available_credits` value at init.
   */
  if (typeof window.collectionLauncher === 'undefined') {
    window.collectionLauncher = function (availableCredits) {
      return {
        designId: '',
        mode: 'batch',
        tier: 'free',
        dateFrom: '',
        dateTo: '',
        availableCredits: availableCredits || 0,
        estimatedCredits: 0,
        launching: false,
        _estimateTimer: null,

        get canLaunch() {
          return this.estimatedCredits <= this.availableCredits;
        },

        init() {
          document.addEventListener('estimate:result', (evt) => {
            this.estimatedCredits = evt.detail.credits || 0;
            this.availableCredits = evt.detail.availableCredits || this.availableCredits;
          });
        },

        requestEstimate() {
          if (!this.designId) return;
          clearTimeout(this._estimateTimer);
          this._estimateTimer = setTimeout(() => {
            const trigger = document.getElementById('estimate-trigger');
            if (trigger) htmx.trigger(trigger, 'estimate');
          }, 400);
        },

        onFormChange() {
          this.requestEstimate();
        },

        onSubmit(event) {
          if (!this.canLaunch || !this.designId) {
            event.preventDefault();
          } else {
            this.launching = true;
          }
        },
      };
    };
  }


  /**
   * flashDismiss — handles dismissing flash messages via Alpine x-show.
   * Used directly inline via x-data="{ show: true }" in flash.html.
   * No global registration needed — kept here as documentation.
   */

});

// ---------------------------------------------------------------------------
// Utility: dispatch a custom event from a server-rendered HTMX fragment.
// The credit_estimate fragment calls this after HTMX swaps it into the DOM.
// ---------------------------------------------------------------------------

/**
 * Dispatch the estimate:result event so the collectionLauncher Alpine
 * component can update its credit gate without parsing the DOM.
 *
 * Called by _fragments/credit_estimate.html via:
 *   dispatchEstimateResult(totalCredits, availableCredits)
 *
 * @param {number} totalCredits     - estimated credits for this run
 * @param {number} availableCredits - current user credit balance
 */
window.dispatchEstimateResult = function (totalCredits, availableCredits) {
  document.dispatchEvent(new CustomEvent('estimate:result', {
    detail: {
      credits: totalCredits,
      availableCredits: availableCredits,
    },
  }));
};

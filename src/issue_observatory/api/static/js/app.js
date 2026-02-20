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
// 1. HTMX global 401 handler
//    When any HTMX request receives a 401, save the current path so the login
//    page can redirect back after a successful login, then navigate to login.
// ---------------------------------------------------------------------------

document.body.addEventListener('htmx:responseError', function (evt) {
  if (evt.detail.xhr.status === 401) {
    sessionStorage.setItem('redirect_after_login', window.location.pathname);
    window.location.href = '/auth/login?session_expired=1';
  }
});

// ---------------------------------------------------------------------------
// 2. HTMX HX-Redirect response header handler
//    HTMX 2 does not follow the HX-Redirect response header automatically
//    for non-boosted requests. We handle it here for all HTMX requests so
//    that the launcher POST (hx-post="/collections/") can redirect the browser
//    to the new run's detail page on success.
// ---------------------------------------------------------------------------

document.body.addEventListener('htmx:afterRequest', function (evt) {
  const redirect = evt.detail.xhr.getResponseHeader('HX-Redirect');
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

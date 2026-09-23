document.querySelectorAll('[data-wizard-form]').forEach(form => {
  form.addEventListener('submit', event => {
    if (form.dataset.submitting) {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = 'true';
    if (event.submitter?.hasAttribute('data-ai-action')) {
      form.querySelector('.wizard-loading').hidden = false;
      form.setAttribute('aria-busy', 'true');
    }
    // Keep the clicked button enabled so its action is included in the POST.
    form.querySelectorAll('button').forEach(button => button.setAttribute('aria-disabled', 'true'));
  });
});
window.addEventListener('pageshow', () => {
  document.querySelectorAll('[data-wizard-form]').forEach(form => {
    delete form.dataset.submitting;
    form.removeAttribute('aria-busy');
    form.querySelectorAll('button').forEach(button => button.removeAttribute('aria-disabled'));
    const loading = form.querySelector('.wizard-loading');
    if (loading) loading.hidden = true;
  });
});

document.querySelectorAll('[data-proposal-form]').forEach(form => {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (form.dataset.busy) return;
    const action = event.submitter?.value;
    if (!action) return;
    const card = form.closest('[data-proposal]');
    const feedback = card.querySelector('[data-proposal-feedback]');
    const body = new FormData(form);
    body.set('action', action);
    form.dataset.busy = 'true';
    form.setAttribute('aria-busy', 'true');
    const buttons = [...form.querySelectorAll('button')];
    buttons.forEach(button => button.disabled = true);
    feedback.textContent = 'Сохраняем решение…';
    feedback.classList.remove('is-error');
    try {
      const response = await fetch(form.getAttribute('action'), {
        method: 'POST', body, credentials: 'same-origin',
        headers: {'Accept': 'application/json'},
      });
      if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Не удалось сохранить решение. Проверьте вход в аккаунт и доступ к задаче.');
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Не удалось сохранить решение. Попробуйте ещё раз.');
      if (!['pending', 'selected', 'rejected'].includes(data.status)) throw new Error('Получен некорректный ответ сервера.');
      const badge = card.querySelector('[data-proposal-status]');
      badge.className = `proposal-status proposal-status--${data.status}`;
      badge.textContent = data.status_label;
      const progressButton = form.querySelector('[value="progress"]');
      if (progressButton) progressButton.hidden = !data.can_confirm_progress;
      card.querySelector('[data-progress-confirmed]').hidden = !data.progress_confirmed;
      form.hidden = data.progress_confirmed;
      feedback.textContent = data.progress_confirmed ? 'Этап подтверждён.' : 'Решение сохранено.';
    } catch (error) {
      feedback.classList.add('is-error');
      feedback.textContent = error instanceof TypeError
        ? 'Связь с сервером прервалась. Решение могло сохраниться — повторите действие или обновите карточку.'
        : error.message;
    } finally {
      delete form.dataset.busy;
      form.removeAttribute('aria-busy');
      buttons.forEach(button => button.disabled = false);
    }
  });
});

(() => {
  const openEditor = dialog => { if (!dialog.open) dialog.showModal(); };
  document.querySelectorAll('[data-edit-profile]').forEach(button => {
    button.addEventListener('click', () => openEditor(document.getElementById('social-editor-' + button.dataset.editProfile)));
  });
  document.querySelectorAll('[data-close-profile]').forEach(button => {
    button.addEventListener('click', () => { const dialog = button.closest('dialog'); dialog.close(); dialog.querySelector('form').reset(); updatePreview(dialog); });
  });
  function updatePreview(dialog) {
    const preview = dialog.querySelector('.social-cover-preview');
    const selected = dialog.querySelector('input[name="portada"]:checked');
    if (preview && selected) preview.className = 'social-cover-preview cover-' + selected.value;
  }
  document.querySelectorAll('.social-dialog').forEach(dialog => {
    dialog.addEventListener('change', () => updatePreview(dialog));
    dialog.addEventListener('cancel', () => { dialog.querySelector('form').reset(); updatePreview(dialog); });
    if (dialog.hasAttribute('data-has-errors')) openEditor(dialog);
  });
})();

/** Presentation only: navigation, file-selection feedback, and response visibility.
 * Authentication, API requests, uploads, and destructive-action confirmation stay
 * in the original application modules.
 */
const viewCopy = {
  upload: ['Upload media', 'Every discovery starts here.', 'Add a photo or video. Let your wildlife collection grow.'],
  explore: ['Explore collection', 'Follow your curiosity.', 'Find your wildlife media by species, tags, or a reference file.'],
  manage: ['Manage media', 'A little care for your collection.', 'Refine species tags and keep your media organised.']
};
function showView(view) {
  if (!viewCopy[view]) return;
  document.querySelectorAll('[data-panel]').forEach(panel => {
    panel.hidden = panel.dataset.panel !== view;
  });
  document.querySelectorAll('.nav-item').forEach(button => {
    const active = button.dataset.view === view;
    button.classList.toggle('is-active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  const [label, title, description] = viewCopy[view];
  document.getElementById('viewBreadcrumb').textContent = label;
  document.getElementById('viewTitle').textContent = title;
  document.getElementById('viewDescription').textContent = description;
}
document.querySelectorAll('[data-view]').forEach(button => {
  button.addEventListener('click', () => {
    showView(button.dataset.view);
    document.getElementById('workspace').focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: 'auto' });
  });
});
const searchTabs = Array.from(document.querySelectorAll('[data-search]'));
function selectSearch(tab) {
  searchTabs.forEach(button => {
    const active = button === tab;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll('[data-search-panel]').forEach(panel => {
    panel.hidden = panel.dataset.searchPanel !== tab.dataset.search;
  });
}
searchTabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectSearch(tab));
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % searchTabs.length;
    if (event.key === 'ArrowLeft') next = (index - 1 + searchTabs.length) % searchTabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = searchTabs.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    selectSearch(searchTabs[next]);
    searchTabs[next].focus();
  });
});
document.querySelectorAll('[data-picker]').forEach(picker => {
  const input = document.getElementById(picker.dataset.picker);
  const label = picker.querySelector('[data-file-label]');
  const refresh = () => {
    const file = input.files[0];
    picker.classList.toggle('has-file', Boolean(file));
    label.textContent = file ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB` : '';
  };
  input.addEventListener('change', refresh);
  ['dragenter', 'dragover'].forEach(name => picker.addEventListener(name, event => {
    event.preventDefault();
    picker.classList.add('is-dragging');
  }));
  picker.addEventListener('dragleave', () => picker.classList.remove('is-dragging'));
  picker.addEventListener('drop', event => {
    event.preventDefault();
    picker.classList.remove('is-dragging');
    const files = event.dataTransfer?.files;
    if (!files?.length) return;
    const transfer = new DataTransfer();
    transfer.items.add(files[0]);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
});
// Keep errors and update outcomes visible even when raw JSON is collapsed.
document.querySelectorAll('.response-details pre').forEach(pre => {
  new MutationObserver(() => {
    let result;
    try { result = JSON.parse(pre.textContent); } catch { return; }
    const details = pre.closest('details');
    const error = Boolean(result?.error);
    details.classList.toggle('has-error', error);
    if (error || ['bulkTagsResult', 'deleteFilesResult'].includes(pre.id)) details.open = true;
  }).observe(pre, { childList: true, characterData: true, subtree: true });
});
showView('upload');

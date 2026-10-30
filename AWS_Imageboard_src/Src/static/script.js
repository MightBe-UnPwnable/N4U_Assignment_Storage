// Progressive enhancement only. Posting and browsing both work fine with
// JavaScript disabled -- this just adds two convenience behaviors.

document.addEventListener('click', function (e) {
  // Click a thumbnail to expand/collapse it inline instead of opening a new tab.
  const thumb = e.target.closest('.thumb');
  if (thumb) {
    e.preventDefault();
    const link = thumb.closest('a');
    if (thumb.dataset.expanded === '1') {
      thumb.src = thumb.dataset.thumbSrc;
      thumb.classList.remove('expanded');
      thumb.dataset.expanded = '0';
    } else {
      thumb.dataset.thumbSrc = thumb.src;
      thumb.src = link.href;
      thumb.classList.add('expanded');
      thumb.dataset.expanded = '1';
    }
    return;
  }

  // Click [Reply] on a post to insert a >>quote into that thread's reply box.
  const quoteBtn = e.target.closest('.quoteBtn');
  if (quoteBtn) {
    const threadId = quoteBtn.dataset.thread;
    const textarea = document.querySelector('.replyTextarea[data-thread="' + threadId + '"]');
    if (textarea) {
      e.preventDefault();
      const insert = '>>' + quoteBtn.dataset.pid + '\n';
      textarea.value = textarea.value ? textarea.value + insert : insert;
      textarea.focus();
      textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    // if the textarea isn't found for some reason, fall through to the
    // href="#pID" anchor jump as a harmless default
  }
});

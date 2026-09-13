(function () {
  function debounce(fn, ms) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

    function renderOption(item) {
    const img = item.image_url
      ? `<img src="${escapeHtml(item.image_url)}" alt="" class="shipment-picker-thumb" loading="lazy">`
      : '<span class="shipment-picker-thumb shipment-picker-thumb-empty" aria-hidden="true"></span>';
    return (
      `<li class="shipment-picker-option" role="option" tabindex="-1"` +
      ` data-id="${item.id}" data-name="${escapeHtml(item.name)}"` +
      ` data-category="${escapeHtml(item.category || '')}">` +
      `${img}` +
      `<div class="shipment-picker-option-body">` +
      `<span class="shipment-picker-option-title">${escapeHtml(item.name)}</span>` +
      `<span class="shipment-picker-option-meta">${escapeHtml(item.category)} · ` +
      `${item.pledged_units}/${item.moq} units · ${escapeHtml(item.status)}</span>` +
      `</div></li>`
    );
  }

  function initPicker(root) {
    const hidden = root.querySelector('[data-shipment-picker-value]');
    const searchInput = root.querySelector('[data-shipment-picker-search]');
    const list = root.querySelector('[data-shipment-picker-list]');
    const selected = root.querySelector('[data-shipment-picker-selected]');
    const searchUrl = root.dataset.searchUrl;
    let initialItems = [];
    const initialScript = document.getElementById(root.dataset.initialScriptId || '');
    if (initialScript) {
      try {
        initialItems = JSON.parse(initialScript.textContent);
      } catch (e) {
        initialItems = [];
      }
    }

    function showList(items) {
      if (!items.length) {
        list.innerHTML = '<li class="shipment-picker-empty">No matching products</li>';
        list.hidden = false;
        return;
      }
      list.innerHTML = items.map(renderOption).join('');
      list.hidden = false;
    }

    function selectItem(item) {
      hidden.value = item.id;
      searchInput.value = '';
      list.hidden = true;
      selected.hidden = false;
      selected.innerHTML =
        (item.image_url
          ? `<img src="${escapeHtml(item.image_url)}" alt="" class="shipment-picker-thumb">`
          : '<span class="shipment-picker-thumb shipment-picker-thumb-empty"></span>') +
        `<div class="shipment-picker-option-body">` +
        `<span class="shipment-picker-option-title">${escapeHtml(item.name)}</span>` +
        `<span class="shipment-picker-option-meta">${escapeHtml(item.category)} · group buy #${item.id}</span>` +
        `</div>` +
        `<button type="button" class="btn btn-link btn-sm shipment-picker-clear">Change</button>`;
      selected.querySelector('.shipment-picker-clear').addEventListener('click', clearSelection);
    }

    function clearSelection() {
      hidden.value = '';
      selected.hidden = true;
      selected.innerHTML = '';
      searchInput.focus();
      showList(initialItems);
    }

    function pickFromList(event) {
      const option = event.target.closest('.shipment-picker-option');
      if (!option) return;
      selectItem({
        id: parseInt(option.dataset.id, 10),
        name: option.dataset.name,
        category: option.dataset.category || '',
        image_url: option.querySelector('img')?.getAttribute('src') || '',
        moq: 0,
        pledged_units: 0,
        status: '',
      });
    }

    const fetchResults = debounce(function () {
      const q = searchInput.value.trim();
      if (!searchUrl) {
        const filtered = initialItems.filter((item) => {
          if (!q) return true;
          const hay = `${item.name} ${item.category} ${item.id}`.toLowerCase();
          return hay.includes(q.toLowerCase());
        });
        showList(filtered);
        return;
      }
      const url = new URL(searchUrl, window.location.origin);
      url.searchParams.set('q', q);
      fetch(url, { headers: { Accept: 'application/json' } })
        .then((r) => r.json())
        .then((data) => showList(data.results || []))
        .catch(() => showList([]));
    }, 200);

    searchInput.addEventListener('focus', () => {
      if (!hidden.value) showList(initialItems);
    });
    searchInput.addEventListener('input', fetchResults);
    list.addEventListener('click', pickFromList);

    document.addEventListener('click', (event) => {
      if (!root.contains(event.target)) list.hidden = true;
    });

    root.closest('form')?.addEventListener('submit', (event) => {
      if (!hidden.value) {
        event.preventDefault();
        searchInput.focus();
        showList(initialItems);
      }
    });
  }

  document.querySelectorAll('[data-shipment-product-picker]').forEach(initPicker);
})();

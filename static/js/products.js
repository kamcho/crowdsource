(function () {
    var grid = document.getElementById('productGrid');
    var sentinel = document.getElementById('productScrollSentinel');
    var loader = document.getElementById('productScrollLoader');
    var endMessage = document.getElementById('productScrollEnd');

    if (!grid || !sentinel) {
        return;
    }

    var loadUrl = grid.dataset.loadUrl;
    var nextPage = grid.dataset.nextPage;
    var hasNext = grid.dataset.hasNext === 'true';
    var loading = false;

    function showLoader() {
        if (loader) {
            loader.hidden = false;
        }
    }

    function hideLoader() {
        if (loader) {
            loader.hidden = true;
        }
    }

    function showEndMessage() {
        if (endMessage) {
            endMessage.hidden = false;
        }
    }

    function buildRequestUrl(page) {
        var params = new URLSearchParams({ page: page });
        if (grid.dataset.category) {
            params.set('category', grid.dataset.category);
        }
        if (grid.dataset.search) {
            params.set('q', grid.dataset.search);
        }
        return loadUrl + '?' + params.toString();
    }

    async function loadMoreProducts() {
        if (loading || !hasNext || !nextPage) {
            return;
        }

        loading = true;
        showLoader();

        try {
            var response = await fetch(buildRequestUrl(nextPage), {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });

            if (!response.ok) {
                throw new Error('Failed to load products');
            }

            var data = await response.json();
            if (data.html) {
                grid.insertAdjacentHTML('beforeend', data.html);
            }

            hasNext = data.has_next;
            nextPage = data.next_page ? String(data.next_page) : '';
            grid.dataset.hasNext = hasNext ? 'true' : 'false';
            grid.dataset.nextPage = nextPage;

            if (!hasNext) {
                observer.disconnect();
                showEndMessage();
            }
        } catch (error) {
            console.error(error);
        } finally {
            loading = false;
            hideLoader();
        }
    }

    var observer = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) {
            loadMoreProducts();
        }
    }, {
        root: null,
        rootMargin: '240px 0px',
        threshold: 0,
    });

    if (hasNext) {
        observer.observe(sentinel);
    } else {
        showEndMessage();
    }
})();

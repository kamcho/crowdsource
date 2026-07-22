(function () {
    'use strict';

    var drawer = document.getElementById('categoryDrawer');
    var dataEl = document.getElementById('category-nav-data');
    if (!drawer || !dataEl) {
        return;
    }

    var tree = [];
    try {
        tree = JSON.parse(dataEl.textContent);
    } catch (err) {
        return;
    }

    var panel = drawer.querySelector('.category-drawer-panel');
    var parentList = drawer.querySelector('.category-drawer-parents');
    var contentEl = drawer.querySelector('.category-drawer-content');
    var slugIndex = {};
    var activeSlug = '';

    function indexNodes(nodes, parent) {
        nodes.forEach(function (node) {
            slugIndex[node.slug] = { node: node, parent: parent || null };
            if (node.children && node.children.length) {
                indexNodes(node.children, node);
            }
        });
    }

    indexNodes(tree, null);

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function placeholderSvg() {
        return '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
            '<rect x="3" y="3" width="7" height="7" rx="1" stroke="currentColor" stroke-width="1.5"/>' +
            '<rect x="14" y="3" width="7" height="7" rx="1" stroke="currentColor" stroke-width="1.5"/>' +
            '<rect x="3" y="14" width="7" height="7" rx="1" stroke="currentColor" stroke-width="1.5"/>' +
            '<rect x="14" y="14" width="7" height="7" rx="1" stroke="currentColor" stroke-width="1.5"/>' +
            '</svg>';
    }

    function viewAllSvg() {
        return '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
            '<path d="M4 7h4M4 12h4M4 17h4M16 7h4M16 12h4M16 17h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
            '</svg>';
    }

    function renderIcon(imageUrl, sizeClass) {
        if (imageUrl) {
            return '<span class="' + sizeClass + '"><img src="' + escapeHtml(imageUrl) + '" alt=""></span>';
        }
        return '<span class="' + sizeClass + '">' + placeholderSvg() + '</span>';
    }

    function renderViewAllTile(url, label) {
        return '<a href="' + escapeHtml(url) + '" class="category-drawer-tile category-drawer-view-all">' +
            '<span class="category-drawer-tile-img">' + viewAllSvg() + '</span>' +
            '<span class="category-drawer-tile-label">' + escapeHtml(label || 'View all') + '</span>' +
            '</a>';
    }

    function findRoot(node) {
        var current = node;
        while (current) {
            var entry = slugIndex[current.slug];
            if (!entry || !entry.parent) {
                return current;
            }
            current = entry.parent;
        }
        return node;
    }
    function renderTile(node, extraClass) {
        var className = 'category-drawer-tile' + (extraClass ? ' ' + extraClass : '');
        return '<a href="' + escapeHtml(node.url) + '" class="' + className + '">' +
            renderIcon(node.image_url, 'category-drawer-tile-img') +
            '<span class="category-drawer-tile-label">' + escapeHtml(node.name) + '</span>' +
            '</a>';
    }

    function renderParentSidebar() {
        parentList.innerHTML = tree.map(function (node) {
            var isActive = node.slug === activeSlug;
            return '<li class="category-drawer-parent' + (isActive ? ' is-active' : '') + '">' +
                '<button type="button" class="category-drawer-parent-btn" data-parent-slug="' + escapeHtml(node.slug) + '">' +
                renderIcon(node.image_url, 'category-drawer-parent-icon') +
                '<span>' + escapeHtml(node.name) + '</span>' +
                '</button></li>';
        }).join('');
    }

    function renderContent(parentNode) {
        if (!parentNode) {
            contentEl.innerHTML = '<p class="category-drawer-empty">No categories available yet.</p>';
            return;
        }

        var html = '<div class="category-drawer-section-header">' +
            '<h3>' + escapeHtml(parentNode.name) + '</h3>' +
            '<a class="category-drawer-browse-all" href="' + escapeHtml(parentNode.url) + '">Browse all</a>' +
            '</div>';

        var groups = [];
        var directTiles = [];

        parentNode.children.forEach(function (child) {
            if (child.children && child.children.length) {
                groups.push(child);
            } else {
                directTiles.push(child);
            }
        });

        if (directTiles.length) {
            html += '<div class="category-drawer-group">' +
                '<div class="category-drawer-grid">';
            directTiles.forEach(function (child) {
                html += renderTile(child);
            });
            html += renderViewAllTile(parentNode.url);
            html += '</div></div>';
        }

        groups.forEach(function (group) {
            html += '<div class="category-drawer-group">' +
                '<div class="category-drawer-group-title">' + escapeHtml(group.name) + '</div>' +
                '<div class="category-drawer-grid">';
            group.children.forEach(function (leaf) {
                html += renderTile(leaf);
            });
            html += renderViewAllTile(group.url);
            html += '</div></div>';
        });

        if (!directTiles.length && !groups.length) {
            html += '<div class="category-drawer-group"><div class="category-drawer-grid">' +
                renderViewAllTile(parentNode.url, 'Browse ' + parentNode.name) +
                '</div></div>';
        }

        contentEl.innerHTML = html;
    }

    function selectParent(slug) {
        var parentNode = null;
        if (slug && slugIndex[slug]) {
            parentNode = findRoot(slugIndex[slug].node);
        } else if (tree.length) {
            parentNode = tree[0];
        }

        activeSlug = parentNode ? parentNode.slug : '';
        renderParentSidebar();
        renderContent(parentNode);
    }

    function openDrawer(startSlug) {
        var initialSlug = '';
        if (startSlug && slugIndex[startSlug]) {
            initialSlug = findRoot(slugIndex[startSlug].node).slug;
        } else if (tree.length) {
            initialSlug = tree[0].slug;
        }

        selectParent(initialSlug);

        drawer.hidden = false;
        drawer.setAttribute('aria-hidden', 'false');
        drawer.classList.add('is-open');
        document.body.classList.add('category-drawer-open');

        requestAnimationFrame(function () {
            drawer.classList.add('is-visible');
        });

        panel.focus();
    }

    function closeDrawer() {
        drawer.classList.remove('is-visible');
        document.body.classList.remove('category-drawer-open');

        window.setTimeout(function () {
            drawer.classList.remove('is-open');
            drawer.hidden = true;
            drawer.setAttribute('aria-hidden', 'true');
        }, 280);
    }

    document.addEventListener('click', function (event) {
        var openTrigger = event.target.closest('[data-category-drawer-open]');
        if (openTrigger) {
            event.preventDefault();
            openDrawer(openTrigger.getAttribute('data-category-slug') || '');
            return;
        }

        if (event.target.closest('[data-category-drawer-close]')) {
            event.preventDefault();
            closeDrawer();
            return;
        }

        var parentBtn = event.target.closest('[data-parent-slug]');
        if (parentBtn && drawer.contains(parentBtn)) {
            event.preventDefault();
            selectParent(parentBtn.getAttribute('data-parent-slug'));
        }
    });

    document.addEventListener('keydown', function (event) {
        if (drawer.hidden || !drawer.classList.contains('is-visible')) {
            return;
        }
        if (event.key === 'Escape') {
            closeDrawer();
        }
    });

    if (window.location.hash === '#categories') {
        window.addEventListener('load', function () {
            openDrawer('');
        });
    }
})();

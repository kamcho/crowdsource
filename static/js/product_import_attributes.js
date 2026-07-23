(function () {
    var dataNode = document.getElementById('attributes-data');
    var tbody = document.getElementById('attributes-body');
    var hiddenInput = document.getElementById('attributes-json');
    var form = document.getElementById('attributes-form');
    if (!dataNode || !tbody || !hiddenInput || !form) return;

    var attributes = JSON.parse(dataNode.textContent || '[]');

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/"/g, '&quot;');
    }

    function render() {
        tbody.innerHTML = '';
        attributes.forEach(function (item, index) {
            var row = document.createElement('tr');
            row.innerHTML =
                '<td><input type="text" class="form-input attr-title" value="' + escapeHtml(item.title) + '"></td>' +
                '<td><input type="text" class="form-input attr-description" value="' + escapeHtml(item.description) + '"></td>' +
                '<td><select class="form-input form-select attr-section">' +
                    '<option value="key"' + (item.section === 'key' ? ' selected' : '') + '>Key attributes</option>' +
                    '<option value="packaging"' + (item.section === 'packaging' ? ' selected' : '') + '>Packaging & delivery</option>' +
                '</select></td>' +
                '<td><button type="button" class="btn btn-outline btn-sm remove-row" data-index="' + index + '">Remove</button></td>';
            tbody.appendChild(row);
        });
        bindRowEvents();
    }

    function bindRowEvents() {
        tbody.querySelectorAll('.remove-row').forEach(function (button) {
            button.addEventListener('click', function () {
                var index = parseInt(button.getAttribute('data-index'), 10);
                attributes.splice(index, 1);
                render();
            });
        });
    }

    function collect() {
        var rows = tbody.querySelectorAll('tr');
        var next = [];
        rows.forEach(function (row, index) {
            var title = row.querySelector('.attr-title').value.trim();
            if (!title) return;
            next.push({
                title: title,
                description: row.querySelector('.attr-description').value.trim(),
                section: row.querySelector('.attr-section').value,
                sort_order: index,
            });
        });
        return next;
    }

    document.getElementById('add-attribute-row').addEventListener('click', function () {
        attributes.push({ title: '', description: '', section: 'key', sort_order: attributes.length });
        render();
    });

    form.addEventListener('submit', function () {
        hiddenInput.value = JSON.stringify(collect());
    });

    render();
})();
